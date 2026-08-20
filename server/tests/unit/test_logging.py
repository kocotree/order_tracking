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


def test_structured_logger_redacts_identity_phone_codes_and_credentials() -> None:
    stream = StringIO()
    logger = StructuredLogger(stream=stream)

    logger.event(
        "identity.test",
        request_id="req-identity-redaction",
        fields={
            "phone": "13812345122",
            "verificationCode": "123456",
            "authorizationCode": "oauth-sensitive-code",
            "accessToken": "access-sensitive-token",
            "refreshToken": "refresh-sensitive-token",
            "safe": "visible",
        },
    )

    rendered = stream.getvalue()
    assert "13812345122" not in rendered
    assert "123456" not in rendered
    assert "oauth-sensitive-code" not in rendered
    assert "access-sensitive-token" not in rendered
    assert "refresh-sensitive-token" not in rendered
    assert json.loads(rendered)["safe"] == "visible"
