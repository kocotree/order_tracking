from dataclasses import dataclass
from typing import Protocol

from app.adapters.errors import ExternalAdapterUnavailable


class ExternalIdentityUnavailable(ExternalAdapterUnavailable):
    pass


@dataclass(frozen=True)
class FeishuProfile:
    subject: str
    display_name: str
    avatar_url: str | None = None


class FeishuIdentity(Protocol):
    @property
    def scope(self) -> str: ...

    def authorization_url(self, *, state: str) -> str: ...

    def exchange_code(self, *, code: str) -> FeishuProfile: ...


class FakeFeishuIdentity:
    def __init__(
        self,
        *,
        profiles: dict[str, FeishuProfile],
        scope: str = "fake-feishu/default",
    ) -> None:
        self._profiles = profiles
        self._scope = scope

    @property
    def scope(self) -> str:
        return self._scope

    def authorization_url(self, *, state: str) -> str:
        return f"https://fake-feishu.invalid/oauth?state={state}"

    def exchange_code(self, *, code: str) -> FeishuProfile:
        try:
            return self._profiles[code]
        except KeyError as error:
            raise ExternalIdentityUnavailable("feishu identity is unavailable") from error


class DisabledFeishuIdentity:
    def __init__(self, *, scope: str) -> None:
        self._scope = scope

    @property
    def scope(self) -> str:
        return self._scope

    def authorization_url(self, *, state: str) -> str:
        del state
        raise ExternalIdentityUnavailable("feishu identity is not configured")

    def exchange_code(self, *, code: str) -> FeishuProfile:
        del code
        raise ExternalIdentityUnavailable("feishu identity is not configured")
