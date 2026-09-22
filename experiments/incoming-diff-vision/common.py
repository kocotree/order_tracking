# /// script
# requires-python = ">=3.11"
# dependencies = ["openai>=1.40"]
# ///

from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
from pathlib import Path

HERE = Path(__file__).parent
IMAGES = HERE / "images"
IMAGES_HOLDOUT = HERE / "images_holdout"
PROMPTS = HERE / "prompts"
RAW = HERE / "raw"
RAW_HOLDOUT = HERE / "raw_holdout"
OUT = HERE / "out"
OUT_HOLDOUT = HERE / "out_holdout"
DATASET = HERE / "dataset.csv"
DATASET_HOLDOUT = HERE / "dataset_holdout.csv"
PRICES = HERE / "prices.json"

SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
MAX_BYTES = 10 * 1024 * 1024  # 百炼单图体积上限
MAX_ATTEMPTS = 3

# 实测（3 张图各 9 次）：图在前 4/9 空输出，文在前 1/9，文在前+预填左括号 0/9。
# 所以固定「文本在前、图片在后」，并用 DashScope partial 模式预填 "{" 逼模型直接写 JSON。
PREFILL = "{"

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def read_prompt(name: str) -> str:
    return (PROMPTS / f"{name}.txt").read_text(encoding="utf-8").strip()


def extract_json(text: str) -> dict | None:
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


def load_env() -> None:
    # .env 里的值只填进本进程环境；已 export 的同名变量优先
    env_file = HERE / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        os.environ.setdefault(name.strip(), value.strip().strip("\"'"))


def load_api_key() -> str:
    load_env()
    key = os.environ["DASHSCOPE_API_KEY"]
    if not key:
        raise SystemExit(f"{HERE/'.env'} 里的 DASHSCOPE_API_KEY 是空的")
    return key


def data_url(path: Path) -> str:
    if path.stat().st_size > MAX_BYTES:
        raise SystemExit(f"{path.name} 超过 10MB，先压缩")
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def images(directory: Path = IMAGES) -> list[Path]:
    found = sorted(p for p in directory.glob("*") if p.suffix.lower() in SUFFIXES)
    if not found:
        raise SystemExit(f"{directory} 里没有图片")
    return found
