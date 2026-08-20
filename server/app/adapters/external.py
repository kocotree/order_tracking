from collections.abc import Mapping
from datetime import datetime
from typing import Any, NoReturn, Protocol


class ExternalIntegrationNotConfigured(RuntimeError):
    pass


class FeishuOrderSource(Protocol):
    def fetch_new_records(self) -> list[Mapping[str, Any]]: ...


class ProductCatalogSource(Protocol):
    def fetch_changed_products(
        self, *, changed_since: datetime | None
    ) -> list[Mapping[str, Any]]: ...


class WeChatIdentityGateway(Protocol):
    def exchange_login_code(self, *, code: str) -> str: ...


class SmsGateway(Protocol):
    def send_verification_code(self, *, phone: str, code: str) -> None: ...


class PrivateObjectStorage(Protocol):
    def put(self, *, object_key: str, content: bytes, content_type: str) -> None: ...

    def get(self, *, object_key: str) -> bytes: ...


class DisabledExternalAdapter:
    def __init__(self, name: str) -> None:
        self._name = name

    def _raise(self) -> NoReturn:
        raise ExternalIntegrationNotConfigured(f"{self._name} is not configured")

    def fetch_new_records(self) -> list[Mapping[str, Any]]:
        self._raise()

    def fetch_changed_products(
        self, *, changed_since: datetime | None
    ) -> list[Mapping[str, Any]]:
        del changed_since
        self._raise()

    def exchange_login_code(self, *, code: str) -> str:
        del code
        self._raise()

    def send_verification_code(self, *, phone: str, code: str) -> None:
        del phone, code
        self._raise()

    def put(self, *, object_key: str, content: bytes, content_type: str) -> None:
        del object_key, content, content_type
        self._raise()

    def get(self, *, object_key: str) -> bytes:
        del object_key
        self._raise()
