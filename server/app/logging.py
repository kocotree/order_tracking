import json
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, TextIO

SENSITIVE_KEY_PARTS = {
    "authorization",
    "cookie",
    "password",
    "phone",
    "secret",
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
