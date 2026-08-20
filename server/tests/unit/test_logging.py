import json
from io import StringIO

from app.logging import StructuredLogger


def test_structured_logger_keeps_request_id_and_redacts_sensitive_fields() -> None:
    stream = StringIO()
    logger = StructuredLogger(stream=stream)

    logger.event(
        "request.completed",
        request_id="req-001",
        fields={"statusCode": 200, "password": "do-not-log", "nested": {"token": "secret"}},
    )

    payload = json.loads(stream.getvalue())
    assert payload["event"] == "request.completed"
    assert payload["requestId"] == "req-001"
    assert payload["statusCode"] == 200
    assert payload["password"] == "[REDACTED]"
    assert payload["nested"]["token"] == "[REDACTED]"
