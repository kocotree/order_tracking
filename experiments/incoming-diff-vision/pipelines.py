from __future__ import annotations

import base64
import io
from pathlib import Path

from PIL import Image

from common import MAX_ATTEMPTS, PREFILL, data_url, extract_json, read_prompt

# 候选方案清单。kind 决定调用结构，其余键决定用哪个模型和哪版提示词。
# 改模型、改提示词都只改这里，不动 bench.py。
# 原选型只在 qwen3.5-plus / qwen3.5-flash / qwen3.5-ocr 之间做；
# qwen3-vl-flash 单段方案为额外对照，控制台当时标记 qwen3-vl-* 即将下线。
PIPELINES = {
    # ① 一段式：一个视觉模型直接出 JSON
    "s1_35plus": {
        "kind": "single",
        "vision": "qwen3.5-plus",
        "prompt": "single_v1",
    },
    "s1_35flash": {
        "kind": "single",
        "vision": "qwen3.5-flash",
        "prompt": "single_v1",
    },
    "s1_vlflash": {
        "kind": "single",
        "vision": "qwen3-vl-flash",
        "prompt": "single_v1",
    },
    "s1_35flash_small": {
        "kind": "single",
        "vision": "qwen3.5-flash",
        "prompt": "single_v1",
        "max_side": 960,
    },
    # 新样本含一图多颜色差异；保留 v1 方案，避免旧结果与新版提示词混用。
    "s1_35flash_color": {
        "kind": "single",
        "vision": "qwen3.5-flash",
        "prompt": "single_v2_color",
    },
    "s1_35flash_small_color": {
        "kind": "single",
        "vision": "qwen3.5-flash",
        "prompt": "single_v2_color",
        "max_side": 960,
    },
    "s1_35plus_color": {
        "kind": "single",
        "vision": "qwen3.5-plus",
        "prompt": "single_v2_color",
    },
    "s1_35plus_small": {
        "kind": "single",
        "vision": "qwen3.5-plus",
        "prompt": "single_v1",
        "max_side": 960,
    },
    "s1_vlflash_small": {
        "kind": "single",
        "vision": "qwen3-vl-flash",
        "prompt": "single_v1",
        "max_side": 960,
    },
    # ② 两段式：OCR 全文 + 纯文本整理
    "s2_ocr_35flash": {
        "kind": "ocr_text",
        "ocr": "qwen3.5-ocr",
        "text": "qwen3.5-flash",
        "structure": "structure_ocr_only_v1",
    },
    # ③ 三段式：专职读标注 + OCR 读箱贴 + 纯文本整理
    "s3_35plus": {
        "kind": "note_ocr_text",
        "note": "qwen3.5-plus",
        "note_prompt": "note_v2",
        "ocr": "qwen3.5-ocr",
        "text": "qwen3.5-flash",
        "structure": "structure_v1",
    },
    "s3_35flash": {
        "kind": "note_ocr_text",
        "note": "qwen3.5-flash",
        "note_prompt": "note_v2",
        "ocr": "qwen3.5-ocr",
        "text": "qwen3.5-flash",
        "structure": "structure_v1",
    },
    "s3_35flash_turbo": {
        "kind": "note_ocr_text",
        "note": "qwen3.5-flash",
        "note_prompt": "note_v2",
        "ocr": "qwen3.5-ocr",
        "text": "qwen-turbo",
        "structure": "structure_v1",
    },
    # note_v1 只问标注不问尺码，对比 note_v2 把尺码一起问会不会把标注问准度带下来
    "s3_35plus_notev1": {
        "kind": "note_ocr_text",
        "note": "qwen3.5-plus",
        "note_prompt": "note_v1",
        "ocr": "qwen3.5-ocr",
        "text": "qwen3.5-flash",
        "structure": "structure_v1",
    },
    # 图片长边压到 960：图片 token 是成本大头，这一项测省钱会不会掉准确率
    "s3_35plus_small": {
        "kind": "note_ocr_text",
        "note": "qwen3.5-plus",
        "note_prompt": "note_v2",
        "ocr": "qwen3.5-ocr",
        "text": "qwen3.5-flash",
        "structure": "structure_v1",
        "max_side": 960,
    },
    # 旧候选，只为和之前跑出来的数据对照；这两个模型都标了即将下线，不参与选型
    "baseline_vlplus": {
        "kind": "note_ocr_text",
        "note": "qwen3-vl-plus",
        "note_prompt": "note_v1",
        "ocr": "qwen3.5-ocr",
        "text": "qwen-plus",
        "structure": "structure_v1",
    },
}


def _image_payload(path: Path, max_side: int | None) -> str:
    if max_side is None:
        return data_url(path)
    with Image.open(path) as im:
        if max(im.size) <= max_side:
            return data_url(path)
        scale = max_side / max(im.size)
        resized = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
        buffer = io.BytesIO()
        resized.convert("RGB").save(buffer, format="JPEG", quality=88)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()


def _usage(stage: str, model: str, response) -> dict:
    usage = response.usage
    return {
        "stage": stage,
        "model": model,
        "in": usage.prompt_tokens,
        "out": usage.completion_tokens,
    }


# qwen3.5 系列默认开思考模式，实测 note 阶段会吐 2500~13900 个思考 token、单张 40~190 秒，
# 还经常思考完不给答案。这三个任务都不需要推理，一律关掉。
NO_THINKING = {"enable_thinking": False}


def _ask_image(client, model: str, prompt: str, path: Path, max_side: int | None):
    # 文本在前、图片在后：实测这个顺序空输出率从 4/9 降到 1/9
    response = client.chat.completions.create(
        model=model,
        extra_body=NO_THINKING,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": _image_payload(path, max_side)}},
                ],
            }
        ],
    )
    return (response.choices[0].message.content or "").strip(), response


def _ask_image_json(client, model: str, prompt: str, path: Path, max_side: int | None):
    response = client.chat.completions.create(
        model=model,
        extra_body=NO_THINKING,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": _image_payload(path, max_side)}},
                ],
            },
            {"role": "assistant", "content": PREFILL, "partial": True},
        ],
    )
    body = response.choices[0].message.content or ""
    # 若 SDK 没把 partial 传过去，模型会自带左括号，这时按原文再解一次
    return extract_json(PREFILL + body) or extract_json(body), body, response


def _ask_text_json(client, model: str, prompt: str):
    response = client.chat.completions.create(
        model=model,
        extra_body=NO_THINKING,
        messages=[
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": PREFILL, "partial": True},
        ],
    )
    body = response.choices[0].message.content or ""
    return extract_json(PREFILL + body) or extract_json(body), body, response


def run_pipeline(client, spec: dict, path: Path):
    max_side = spec.get("max_side")
    stages: list[dict] = []
    texts: dict[str, str] = {}

    if spec["kind"] == "single":
        for _ in range(MAX_ATTEMPTS):
            parsed, body, response = _ask_image_json(client, spec["vision"], read_prompt(spec["prompt"]), path, max_side)
            stages.append(_usage("single", spec["vision"], response))
            texts["single"] = body
            if parsed is not None:
                return parsed, stages, texts, None
        return None, stages, texts, "非 JSON 输出"

    # 看图的阶段只跑一次，重试只重跑纯文本阶段，不重复付图片的钱
    note_text = ""
    if spec["kind"] == "note_ocr_text":
        note_text, response = _ask_image(client, spec["note"], read_prompt(spec["note_prompt"]), path, max_side)
        stages.append(_usage("note", spec["note"], response))
        texts["note"] = note_text

    ocr_text, response = _ask_image(client, spec["ocr"], read_prompt("ocr_v1"), path, max_side)
    stages.append(_usage("ocr", spec["ocr"], response))
    texts["ocr"] = ocr_text

    prompt = read_prompt(spec["structure"]).replace("{ocr_text}", ocr_text)
    if "{note_text}" in prompt:
        prompt = prompt.replace("{note_text}", note_text or "无")

    for _ in range(MAX_ATTEMPTS):
        parsed, body, response = _ask_text_json(client, spec["text"], prompt)
        stages.append(_usage("structure", spec["text"], response))
        texts["structure"] = body
        if parsed is not None:
            return parsed, stages, texts, None
    return None, stages, texts, "整理阶段非 JSON 输出"
