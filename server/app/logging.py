import json
import logging
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, TextIO

SENSITIVE_KEY_PARTS = {
    "authorization",
    "cookie",
    "logincode",
    "password",
    "phone",
    "secret",
    "sessionkey",
    "token",
    "verificationcode",
}


def is_sensitive_key(key: object) -> bool:
    normalized = str(key).lower().replace("_", "").replace("-", "")
    return any(part in normalized for part in SENSITIVE_KEY_PARTS)


def redact_sensitive(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]" if is_sensitive_key(key) else redact_sensitive(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    return value


class UvicornAccessQueryFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if record.name != "uvicorn.access" or not isinstance(args, tuple) or len(args) < 3:
            return True
        request_target = args[2]
        if not isinstance(request_target, str) or "?" not in request_target:
            return True
        sanitized_args = list(args)
        sanitized_args[2] = request_target.partition("?")[0]
        record.args = tuple(sanitized_args)
        return True


def configure_uvicorn_access_log_redaction() -> None:
    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, UvicornAccessQueryFilter) for item in access_logger.filters):
        access_logger.addFilter(UvicornAccessQueryFilter())


class StructuredLogger:
    def __init__(self, *, stream: TextIO | None = None) -> None:
        self._stream = stream or sys.stdout

    def event(self, event: str, *, request_id: str, fields: Mapping[str, Any]) -> None:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "event": event,
            "requestId": request_id,
            **redact_sensitive(fields),
        }
        self._stream.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
        self._stream.flush()
