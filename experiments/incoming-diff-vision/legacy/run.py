# /// script
# requires-python = ">=3.11"
# dependencies = ["openai>=1.40"]
# ///
"""来货出入图片识别 · 阿里云百炼 VL 模型试水脚本。

对应《来货出入技术设计》第 5 节的固定 JSON schema 与提示词要求，只做离线试跑，
不写数据库、不生成正式记录、不接 server/ 代码。

用法：
    uv run run.py                  # 默认模型跑 images/ 下所有图
    uv run run.py qwen3-vl-plus    # 换模型跑同一组图，便于逐字段对比
    uv run run.py --selftest       # 只跑内部自检，不调 API、不花钱

API Key 放在本目录 .env 里（`DASHSCOPE_API_KEY=sk-...`）。该文件由
.gitignore 忽略，key 不进仓库、不进日志。
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
IMAGES = HERE / "images"
RESULTS = HERE / "results"
SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

DEFAULT_MODEL = "qwen-vl-max"
DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
MAX_IMAGES = 10  # 付费调用，超过要显式 --all
MAX_BYTES = 10 * 1024 * 1024  # 百炼单图体积上限，超了先压缩
MAX_ATTEMPTS = 3  # 兜底重试；顺序+预填修好后实测已很少触发

# 实测（3 张图各 9 次）：图在前 4/9 空输出，文在前 1/9，文在前+预填左括号 0/9。
# 所以固定「文本在前、图片在后」，并用 DashScope partial 模式预填 "{" 逼模型直接写 JSON。
PREFILL = "{"

PROMPT = """你在识别一张服装工厂来货核对用的照片。照片内容通常是纸箱箱贴，上面可能有手写数字、涂改和标注。

只输出一个 JSON 对象，不要输出解释、前后缀或代码块标记，结构固定为：
{
  "factoryName": 工厂名称 或 null,
  "productCode": 产品编号/货号 或 null,
  "productName": 产品名称 或 null,
  "color": 主要颜色 或 null,
  "size": 主要尺码 或 null,
  "businessDate": 日期，按图上原样返回（例如 "9/15"、"2026-09-15"），不要补全年份，或 null,
  "lines": [ {"color": 颜色 或 null, "size": 尺码 或 null, "quantity": 数量数字} ],
  "confidence": 0 到 1 之间的数字，表示你对本次整体识别的确信程度,
  "unresolvedFields": [ 你无法确定的字段名 ]
}

规则：
1. 箱贴印刷内容作为默认值；出现手写、涂改或标注时以手写／涂改／标注为准。
2. 图上没有写明的字段返回 null，不要猜测，不要用常识补全。
3. quantity 按图上写的数字原样返回；正负的业务含义由系统判断，你不要自己加减或改符号。
4. 同一张图上有多个颜色／尺码／数量组合时，每个组合在 lines 里单独一项，不合并、不累加。
5. 只输出 JSON。"""

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def extract_json(text: str) -> dict | None:
    """模型偶尔会用 ```json 包裹或在 JSON 前后带一句客套话，这里尽量抠出对象。"""
    stripped = _FENCE.sub("", text).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    start, end = stripped.find("{"), stripped.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(stripped[start : end + 1])
        except json.JSONDecodeError:
            pass
    return None


def load_api_key() -> str:
    """.env 里的值只填进本进程环境；已 export 的同名变量优先。"""
    env_file = HERE / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            os.environ.setdefault(name.strip(), value.strip().strip("\"'"))
    key = os.environ.get("DASHSCOPE_API_KEY", "")
    if not key:
        sys.exit(f"缺少 API Key：请在 {env_file} 写入一行 DASHSCOPE_API_KEY=sk-你的key")
    return key


def data_url(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def selftest() -> None:
    assert extract_json('{"a": 1}') == {"a": 1}
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('好的，结果如下：\n{"a": 1}\n希望有帮助') == {"a": 1}
    assert extract_json("完全不是 JSON") is None
    print("selftest ok")


def main(argv: list[str]) -> None:
    if "--selftest" in argv:
        selftest()
        return

    positional = [a for a in argv if not a.startswith("-")]
    model = positional[0] if positional else DEFAULT_MODEL

    paths = sorted(p for p in IMAGES.glob("*") if p.suffix.lower() in SUFFIXES)
    if not paths:
        sys.exit(f"{IMAGES} 里没有图片，放几张进去再跑。")
    limit = next((int(a.split("=", 1)[1]) for a in argv if a.startswith("--limit=")), None)
    if limit:
        paths = paths[:limit]  # 先试通链路再全量，省掉一次全量的钱
    elif len(paths) > MAX_IMAGES and "--all" not in argv:
        sys.exit(f"发现 {len(paths)} 张图，超过 {MAX_IMAGES} 张；这是付费调用，确认全跑请加 --all。")
    oversized = [p.name for p in paths if p.stat().st_size > MAX_BYTES]
    if oversized:
        sys.exit(f"以下图片超过 10MB，先压缩再跑：{', '.join(oversized)}")

    from openai import OpenAI

    client = OpenAI(
        api_key=load_api_key(),
        base_url=os.environ.get("DASHSCOPE_BASE_URL", DEFAULT_BASE_URL),
    )

    results = []
    for index, path in enumerate(paths, 1):
        print(f"\n[{index}/{len(paths)}] {path.name}  model={model}")
        started = time.perf_counter()
        tokens_in = tokens_out = 0
        parsed, raw, finish_reason, error = None, "", None, None

        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": PROMPT},
                                {"type": "image_url", "image_url": {"url": data_url(path)}},
                            ],
                        },
                        {"role": "assistant", "content": PREFILL, "partial": True},
                    ],
                )
            except Exception as exc:  # 单张失败不中断整组，便于一次跑完再看
                error = f"{type(exc).__name__}: {exc}"
                print(f"  第 {attempt} 次调用失败：{error}")
                continue

            choice = response.choices[0]
            finish_reason = choice.finish_reason
            body = choice.message.content or ""
            raw = PREFILL + body
            usage = response.usage
            tokens_in += getattr(usage, "prompt_tokens", 0) if usage else 0
            tokens_out += getattr(usage, "completion_tokens", 0) if usage else 0
            # 若 SDK 没把 partial 传过去，模型会自带左括号，这时按原文再解一次
            parsed = extract_json(raw) or extract_json(body)
            if parsed is not None:
                error = None
                break
            error = "空内容" if not body.strip() else "非 JSON 输出"
            print(f"  第 {attempt} 次{error}（finish_reason={finish_reason}），重试")

        elapsed = time.perf_counter() - started
        print(f"  {elapsed:.1f}s  tokens in/out = {tokens_in}/{tokens_out}")
        if parsed is None:
            print(f"  {MAX_ATTEMPTS} 次仍失败：{error}\n{raw!r}")
        else:
            print(json.dumps(parsed, ensure_ascii=False, indent=2))

        results.append(
            {
                "image": path.name,
                "model": model,
                "elapsed_s": round(elapsed, 1),
                "tokens": {"in": tokens_in, "out": tokens_out},
                "finish_reason": finish_reason,
                "parsed": parsed,
                "raw": None if parsed is not None else raw,
                "error": error,
            }
        )

    RESULTS.mkdir(exist_ok=True)
    out_file = RESULTS / f"{model}.json"
    out_file.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    failed = sum(1 for r in results if r.get("parsed") is None)
    print(f"\n共 {len(results)} 张，未拿到有效 JSON {failed} 张；结果写入 results/{out_file.name}")


if __name__ == "__main__":
    main(sys.argv[1:])
