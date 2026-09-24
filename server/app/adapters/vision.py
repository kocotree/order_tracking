import base64
import json
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx

MODEL = "qwen3.5-flash"
PROMPT = (Path(__file__).resolve().parent.parent / "modules" / "incoming_differences"
          / "prompts" / "single_v12_boxes.txt").read_text(encoding="utf-8").strip()


class VisionRecognitionError(ValueError):
    pass


class IncomingDiffRecognizer(Protocol):
    def recognize(self, *, content: bytes, mime_type: str) -> str: ...


class FakeIncomingDiffRecognizer:
    def __init__(self, responses: list[str | Exception]) -> None:
        self.responses = responses
        self.calls = 0

    def recognize(self, *, content: bytes, mime_type: str) -> str:
        self.calls += 1
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class DisabledIncomingDiffRecognizer:
    def recognize(self, *, content: bytes, mime_type: str) -> str:
        raise VisionRecognitionError("vision_unconfigured")


class QwenIncomingDiffRecognizer:
    def __init__(
        self, *, api_key: str, base_url: str, transport: httpx.BaseTransport | None = None
    ):
        if not api_key:
            raise ValueError("vision API key is required")
        parsed_url = urlparse(base_url)
        if (parsed_url.scheme != "https" or not parsed_url.hostname
                or parsed_url.username or parsed_url.password
                or parsed_url.query or parsed_url.fragment):
            raise ValueError("vision API URL must be HTTPS without credentials or query")
        self._key = api_key
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._transport = transport

    def recognize(self, *, content: bytes, mime_type: str) -> str:
        if mime_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise VisionRecognitionError("unsupported_image_type")
        encoded = base64.b64encode(content).decode("ascii")
        with httpx.Client(timeout=60, transport=self._transport) as client:
            response = client.post(
                self._url,
                headers={"Authorization": f"Bearer {self._key}"},
                json={
                    "model": MODEL,
                    "enable_thinking": False,
                    "messages": [{"role": "user", "content": [
                        {"type": "text", "text": PROMPT},
                        {"type": "image_url", "image_url": {
                            "url": f"data:{mime_type};base64,{encoded}"}},
                    ]}, {"role": "assistant", "content": "{", "partial": True}],
                },
            )
            response.raise_for_status()
        answer = response.json()["choices"][0]["message"]["content"]
        if not isinstance(answer, str):
            raise VisionRecognitionError("invalid_model_response")
        return answer if answer.lstrip().startswith("{") else "{" + answer


def parse_vision_result(raw: str) -> dict[str, Any]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as error:
        raise VisionRecognitionError("invalid_json") from error
    if not isinstance(data, dict):
        raise VisionRecognitionError("invalid_json_shape")
    required = {
        "factoryName", "productCode", "productName", "boxes", "diffNoteText",
        "lines", "confidence", "unresolvedFields",
    }
    if not required <= data.keys():
        raise VisionRecognitionError("missing_fields")
    for name in ("factoryName", "productCode", "productName", "diffNoteText"):
        if data[name] is not None and not isinstance(data[name], str):
            raise VisionRecognitionError("invalid_field")
    if not isinstance(data["boxes"], list) or not all(
        isinstance(box, dict) and all(
            name in box and (box[name] is None or isinstance(box[name], str))
            for name in ("color", "size")
        ) for box in data["boxes"]
    ):
        raise VisionRecognitionError("invalid_boxes")
    if not isinstance(data["lines"], list):
        raise VisionRecognitionError("invalid_lines")
    if not isinstance(data["unresolvedFields"], list) or not all(
        isinstance(name, str) for name in data["unresolvedFields"]
    ):
        raise VisionRecognitionError("invalid_unresolved_fields")
    confidence = data["confidence"]
    if (isinstance(confidence, bool) or not isinstance(confidence, (int, float))
            or not 0 <= confidence <= 1):
        raise VisionRecognitionError("invalid_confidence")
    normalized = []
    for line in data["lines"]:
        if (not isinstance(line, dict)
                or not {"color", "size", "direction", "quantity"} <= line.keys()):
            raise VisionRecognitionError("invalid_line")
        if line["color"] is not None and not isinstance(line["color"], str):
            raise VisionRecognitionError("invalid_color")
        if line["size"] is not None and not isinstance(line["size"], str):
            raise VisionRecognitionError("invalid_size")
        if line["direction"] not in ("多", "少"):
            raise VisionRecognitionError("invalid_direction")
        quantity = line["quantity"]
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            raise VisionRecognitionError("invalid_quantity")
        normalized.append({
            "color": line["color"], "size": line["size"],
            "direction": line["direction"], "quantity": quantity,
            "signedQuantity": quantity if line["direction"] == "多" else -quantity,
        })
    return {name: data[name] for name in required - {"lines"}} | {"lines": normalized}
