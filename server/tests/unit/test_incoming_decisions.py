import json

import httpx
import pytest

from app.adapters.incoming_decisions import QwenDecisionParser


@pytest.mark.parametrize("answer", [
    {"ambiguous": True, "decisions": []},
    {"ambiguous": False, "decisions": [{"number": True, "action": "skip"}]},
    {"ambiguous": False, "decisions": [{"number": 9, "action": "skip"}]},
    {"ambiguous": False, "decisions": [{"number": 1, "action": "confirm"}]},
    {"ambiguous": False, "decisions": [{"number": 1, "action": "skip"},
                                        {"number": 1, "action": "register_new"}]},
])
def test_invalid_or_ambiguous_model_output_is_rejected(answer) -> None:
    parser = QwenDecisionParser(api_key="test", base_url="https://model.example/v1",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={
            "choices": [{"message": {"content": json.dumps(answer)}}]})))
    with pytest.raises(ValueError):
        parser.parse(text="这些处理一下", numbers=[1, 2])


def test_explicit_decisions_use_non_thinking_json_without_images() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["enable_thinking"] is False
        assert body["response_format"] == {"type": "json_object"}
        assert body["model"] == "qwen3.5-flash"
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({
            "ambiguous": False, "decisions": [{"number": 1, "action": "skip"},
                                                {"number": 2, "action": "register_new"}]})}}]})
    parser = QwenDecisionParser(api_key="test", base_url="https://model.example/v1",
                                transport=httpx.MockTransport(respond))
    assert parser.parse(text="第1条跳过，第2条作为新记录登记", numbers=[1, 2]) == [
        {"number": 1, "action": "skip"}, {"number": 2, "action": "register_new"}]
