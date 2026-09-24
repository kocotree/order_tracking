import json

import httpx
import pytest

from app.adapters.vision import (
    MODEL,
    PROMPT,
    QwenIncomingDiffRecognizer,
    VisionRecognitionError,
    parse_vision_result,
)


def _result(direction: str = "少", quantity: object = 2) -> str:
    return json.dumps({
        "factoryName": None, "productCode": "KQ123", "productName": "裤子",
        "boxes": [{"color": "暮山紫", "size": "120"}],
        "diffNoteText": "120少2",
        "lines": [{"color": "暮山紫", "size": "120",
                   "direction": direction, "quantity": quantity}],
        "confidence": 0.8, "unresolvedFields": ["factoryName"],
    }, ensure_ascii=False)


def test_v12_signed_quantities_and_unknown_fields() -> None:
    shortage = parse_vision_result(_result())
    surplus = parse_vision_result(_result("多", 3))
    assert shortage["lines"][0]["signedQuantity"] == -2
    assert surplus["lines"][0]["signedQuantity"] == 3
    assert shortage["factoryName"] is None
    assert shortage["unresolvedFields"] == ["factoryName"]
    assert shortage["boxes"] == [{"color": "暮山紫", "size": "120"}]
    assert shortage["diffNoteText"] == "120少2"


@pytest.mark.parametrize("raw", ["{", _result("错"), _result(quantity=0),
                                 _result(quantity=-1), _result(quantity="2")])
def test_v12_invalid_output_fails(raw: str) -> None:
    with pytest.raises(VisionRecognitionError):
        parse_vision_result(raw)


def test_qwen_uses_one_image_call_and_versioned_prompt() -> None:
    requests: list[dict[str, object]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        return httpx.Response(200, json={"choices": [{"message": {"content": _result()}}]})

    adapter = QwenIncomingDiffRecognizer(
        api_key="fake-test-key", base_url="https://example.invalid/compatible-mode/v1",
        transport=httpx.MockTransport(handle),
    )
    assert adapter.recognize(content=b"fake-image", mime_type="image/jpeg") == _result()
    assert len(requests) == 1
    assert requests[0]["model"] == MODEL == "qwen3.5-flash"
    assert requests[0]["enable_thinking"] is False
    content = requests[0]["messages"][0]["content"]  # type: ignore[index]
    assert content[0]["text"] == PROMPT
    assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert requests[0]["messages"][1] == {"role": "assistant", "content": "{", "partial": True}


def test_qwen_rejects_insecure_api_url() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        QwenIncomingDiffRecognizer(api_key="fake-test-key", base_url="http://example.invalid")
