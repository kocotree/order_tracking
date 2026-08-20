from dataclasses import dataclass
from typing import Protocol

from app.adapters.errors import ExternalAdapterUnavailable


class WechatUnavailable(ExternalAdapterUnavailable):
    pass


@dataclass(frozen=True)
class WechatProfile:
    subject: str
    avatar_url: str | None = None


class WechatIdentity(Protocol):
    @property
    def scope(self) -> str: ...

    def exchange_login_code(self, *, code: str) -> WechatProfile: ...

    def exchange_phone_code(self, *, code: str) -> str: ...


class FakeWechatIdentity:
    def __init__(
        self,
        *,
        scope: str,
        login_profiles: dict[str, WechatProfile],
        phone_codes: dict[str, str],
    ) -> None:
        self._scope = scope
        self._login_profiles = login_profiles
        self._phone_codes = phone_codes

    @property
    def scope(self) -> str:
        return self._scope

    def exchange_login_code(self, *, code: str) -> WechatProfile:
        try:
            return self._login_profiles[code]
        except KeyError as error:
            raise WechatUnavailable("wechat identity is unavailable") from error

    def exchange_phone_code(self, *, code: str) -> str:
        try:
            return self._phone_codes[code]
        except KeyError as error:
            raise WechatUnavailable("wechat phone is unavailable") from error


class DisabledWechatIdentity:
    def __init__(self, *, scope: str) -> None:
        self._scope = scope

    @property
    def scope(self) -> str:
        return self._scope

    def exchange_login_code(self, *, code: str) -> WechatProfile:
        del code
        raise WechatUnavailable("wechat identity is not configured")

    def exchange_phone_code(self, *, code: str) -> str:
        del code
        raise WechatUnavailable("wechat identity is not configured")
