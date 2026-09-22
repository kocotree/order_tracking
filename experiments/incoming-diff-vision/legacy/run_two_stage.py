# /// script
# requires-python = ">=3.11"
# dependencies = ["openai>=1.40"]
# ///
"""来货出入图片识别 · 三段方案（专问标注 + OCR 箱贴 → 文本模型整理成 JSON）。

与单阶段 run.py 对照用：同一组图、同一目标 schema，只换实现路径。
    uv run run_two_stage.py            # 跑 images/ 下所有图
    uv run run_two_stage.py --limit=3
    uv run run_two_stage.py --selftest

为什么拆三段（都是实测结论，不是设计偏好）：
- qwen3.5-ocr 一旦输出 html/表格，就只认箱贴、丢掉表外的叠加标注；4 张漏标注的图 OCR
  文本里连「多/少」都没有。改提示词禁表格只救回 3/4，不可靠。
- 反过来，qwen3-vl-plus 被单独问「那条彩色标注写了什么」时 15/15 全部答出，已知真值的
  5 张全对。所以「读标注」和「读箱贴」拆成两个专职提问，各用擅长的模型。
- 阶段三是纯文本任务，把两段文字合并成 JSON，不再需要看图。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from run import (
    IMAGES,
    MAX_ATTEMPTS,
    MAX_BYTES,
    MAX_IMAGES,
    PREFILL,
    RESULTS,
    SUFFIXES,
    data_url,
    extract_json,
    load_api_key,
)

NOTE_MODEL = "qwen3-vl-plus"
OCR_MODEL = "qwen3.5-ocr"
TEXT_MODEL = "qwen-plus"

NOTE_PROMPT = (
    "这张照片上叠加了一条后期加的彩色大字标注（红色、绿色或橙色底的白字），内容形如"
    "「多10」「少2」「120少1，130多1」「m少一个.XL多一个」。请只把这条标注的文字原样输出，"
    "不要输出箱贴上的任何内容，不要解释。如果照片上没有这种叠加标注，只输出：无"
)

OCR_PROMPT = "提取图中所有文字，包括箱贴内容、手写内容和叠加的彩色标注文字，保留原样。"

STRUCTURE_PROMPT = """下面是一张服装工厂来货核对照片的两份识别结果：一份是照片上叠加的彩色标注文字，一份是箱贴的 OCR 文字。

整理成一个 JSON 对象。**差异数量只来自「叠加标注」**，例如「多10」「150少1，140多1」中的 10、1、1；箱贴上「装箱数量」那行的数字**不是**差异数量，两者不要混。

只输出 JSON，不要解释、不要代码块标记，结构固定为：
{
  "factoryName": 工厂名称 或 null,
  "productCode": 货号 或 null,
  "productName": 品名 或 null,
  "color": 颜色 或 null,
  "businessDate": 发货日期，按原样返回（如 "7.31"、"2026.8.11"），不补年份，或 null,
  "packQuantity": 箱贴上的装箱数量数字 或 null（仅作参考，不是差异数量）,
  "diffNoteText": 叠加标注的原文整句 或 null,
  "lines": [ {"size": 尺码, "direction": "多" 或 "少", "quantity": 差异数量的绝对值数字} ],
  "confidence": 0 到 1 的数字,
  "unresolvedFields": [ 读不出的字段名 ]
}

规则：
1. `lines` 只放差异，标注里有几个尺码就拆几条；标注为「无」时 `lines` 为空数组、`diffNoteText` 为 null。
2. 标注没写尺码时（如只写「少2」），该条 `size` 填 null，不要拿箱贴上的尺码去补。
3. `direction` 保留「多」或「少」的原文判断，不要换成正负号——符号由系统转换。
4. `quantity` 填绝对值数字，「少一个」记作 1，「多10」记作 10。
5. 两份识别结果里都没有的字段返回 null，不要猜测、不要用常识补全。
6. 只输出 JSON。

叠加标注识别结果：
---
{note_text}
---

箱贴 OCR 结果：
---
{ocr_text}
---"""


def selftest() -> None:
    for placeholder in ("{note_text}", "{ocr_text}"):
        assert placeholder in STRUCTURE_PROMPT, f"阶段三提示词缺占位符 {placeholder}"
    filled = STRUCTURE_PROMPT.replace("{note_text}", "120少1，130多1").replace("{ocr_text}", "工厂：豆豆")
    assert "豆豆" in filled and "120少1" in filled and "{" in filled
    assert "{note_text}" not in filled and "{ocr_text}" not in filled
    print("selftest ok")


def annotate(client, path: Path):
    """只问那条彩色标注，别的一概不问——问得越窄，答得越准。"""
    response = client.chat.completions.create(
        model=NOTE_MODEL,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": NOTE_PROMPT},
                    {"type": "image_url", "image_url": {"url": data_url(path)}},
                ],
            }
        ],
    )
    return (response.choices[0].message.content or "").strip(), response.usage


def ocr(client, path: Path) -> str:
    response = client.chat.completions.create(
        model=OCR_MODEL,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": OCR_PROMPT},
                    {"type": "image_url", "image_url": {"url": data_url(path)}},
                ],
            }
        ],
    )
    return response.choices[0].message.content or "", response.usage


def structure(client, note_text: str, ocr_text: str):
    prompt = STRUCTURE_PROMPT.replace("{note_text}", note_text).replace("{ocr_text}", ocr_text)
    response = client.chat.completions.create(
        model=TEXT_MODEL,
        messages=[
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": PREFILL, "partial": True},
        ],
    )
    body = response.choices[0].message.content or ""
    return extract_json(PREFILL + body) or extract_json(body), body, response.usage


def main(argv: list[str]) -> None:
    if "--selftest" in argv:
        selftest()
        return

    paths = sorted(p for p in IMAGES.glob("*") if p.suffix.lower() in SUFFIXES)
    if not paths:
        sys.exit(f"{IMAGES} 里没有图片。")
    limit = next((int(a.split("=", 1)[1]) for a in argv if a.startswith("--limit=")), None)
    if limit:
        paths = paths[:limit]
    elif len(paths) > MAX_IMAGES and "--all" not in argv:
        sys.exit(f"发现 {len(paths)} 张图，超过 {MAX_IMAGES} 张；付费调用，确认全跑请加 --all。")
    if any(p.stat().st_size > MAX_BYTES for p in paths):
        sys.exit("有图片超过 10MB，先压缩。")

    from openai import OpenAI

    client = OpenAI(api_key=load_api_key(), base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")

    results = []
    for index, path in enumerate(paths, 1):
        print(f"\n[{index}/{len(paths)}] {path.name}")
        started = time.perf_counter()
        tokens = {"note_in": 0, "note_out": 0, "ocr_in": 0, "ocr_out": 0, "text_in": 0, "text_out": 0}
        parsed, note_text, ocr_text, error = None, "", "", None

        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                # 看图的两段各只跑一次成功即缓存，重试只重跑纯文本的阶段三，不重复付图片的钱
                if not note_text:
                    note_text, usage = annotate(client, path)
                    tokens["note_in"] += getattr(usage, "prompt_tokens", 0)
                    tokens["note_out"] += getattr(usage, "completion_tokens", 0)
                if not ocr_text:
                    ocr_text, usage = ocr(client, path)
                    tokens["ocr_in"] += getattr(usage, "prompt_tokens", 0)
                    tokens["ocr_out"] += getattr(usage, "completion_tokens", 0)
                if not ocr_text.strip() and not note_text.strip():
                    error = "两段识别都返回空"
                    print(f"  第 {attempt} 次 {error}，重试")
                    continue
                parsed, body, usage = structure(client, note_text or "无", ocr_text)
                tokens["text_in"] += getattr(usage, "prompt_tokens", 0)
                tokens["text_out"] += getattr(usage, "completion_tokens", 0)
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                print(f"  第 {attempt} 次调用失败：{error}")
                continue
            if parsed is not None:
                error = None
                break
            error = "阶段三非 JSON 输出"
            print(f"  第 {attempt} 次 {error}，重试")

        elapsed = time.perf_counter() - started
        print(f"  {elapsed:.1f}s  标注={note_text[:24]!r}")
        if parsed is None:
            print(f"  失败：{error}")
        else:
            print(json.dumps(parsed, ensure_ascii=False, indent=2))

        results.append(
            {
                "image": path.name,
                "pipeline": f"{NOTE_MODEL} + {OCR_MODEL} + {TEXT_MODEL}",
                "elapsed_s": round(elapsed, 1),
                "tokens": tokens,
                "note_text": note_text,
                "ocr_text": ocr_text,
                "parsed": parsed,
                "error": error,
            }
        )

    RESULTS.mkdir(exist_ok=True)
    out_file = RESULTS / f"three-stage_{OCR_MODEL}_{TEXT_MODEL}.json"
    out_file.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    failed = sum(1 for r in results if r["parsed"] is None)
    print(f"\n共 {len(results)} 张，失败 {failed} 张；结果写入 results/{out_file.name}")


if __name__ == "__main__":
    main(sys.argv[1:])
