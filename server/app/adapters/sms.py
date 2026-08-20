from typing import Protocol

from app.adapters.errors import ExternalAdapterUnavailable


class SmsUnavailable(ExternalAdapterUnavailable):
    pass


class SmsSender(Protocol):
    def send_code(self, *, phone: str, code: str) -> None: ...


class FakeSmsSender:
    def __init__(self) -> None:
        self._codes: dict[str, str] = {}

    def send_code(self, *, phone: str, code: str) -> None:
        self._codes[phone] = code

    def last_code_for(self, phone: str) -> str:
        return self._codes[phone]


class DisabledSmsSender:
    def send_code(self, *, phone: str, code: str) -> None:
        del phone, code
        raise SmsUnavailable("SMS sender is not configured")
