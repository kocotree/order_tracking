import re
from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol
from urllib.parse import urlencode

import httpx

from app.adapters.errors import ExternalAdapterUnavailable


class ExternalIdentityUnavailable(ExternalAdapterUnavailable):
    pass


@dataclass(frozen=True)
class FeishuProfile:
    subject: str
    display_name: str
    avatar_url: str | None = None
    phone: str | None = None


class FeishuIdentity(Protocol):
    @property
    def scope(self) -> str: ...

    def authorization_url(self, *, state: str) -> str: ...

    def exchange_code(self, *, code: str) -> FeishuProfile: ...


@dataclass(frozen=True)
class FeishuIdentityConfig:
    app_id: str
    app_secret: str
    redirect_uri: str
    authorization_url: str = "https://accounts.feishu.cn/open-apis/authen/v1/authorize"
    token_url: str = "https://accounts.feishu.cn/oauth/v3/token"
    user_info_url: str = "https://open.feishu.cn/open-apis/authen/v1/user_info"


class AppCredentialFeishuIdentity:
    def __init__(
        self,
        config: FeishuIdentityConfig,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._config = config
        self._transport = transport
        app_digest = sha256(config.app_id.encode()).hexdigest()[:32]
        self._scope = f"feishu-app/{app_digest}"

    @property
    def scope(self) -> str:
        return self._scope

    def authorization_url(self, *, state: str) -> str:
        query = urlencode(
            {
                "client_id": self._config.app_id,
                "response_type": "code",
                "scope": "contact:user.phone:readonly",
                "redirect_uri": self._config.redirect_uri,
                "state": state,
            }
        )
        return f"{self._config.authorization_url}?{query}"

    def exchange_code(self, *, code: str) -> FeishuProfile:
        try:
            with httpx.Client(timeout=30, transport=self._transport) as client:
                token_response = client.post(
                    self._config.token_url,
                    json={
                        "grant_type": "authorization_code",
                        "client_id": self._config.app_id,
                        "client_secret": self._config.app_secret,
                        "code": code,
                        "redirect_uri": self._config.redirect_uri,
                    },
                )
                token_response.raise_for_status()
                token_payload = token_response.json()
                if token_payload.get("code", 0) != 0:
                    raise ValueError("feishu token exchange failed")
                access_token = self._required_text(token_payload, "access_token")

                profile_response = client.get(
                    self._config.user_info_url,
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                profile_response.raise_for_status()
                profile_payload = profile_response.json()
                if profile_payload.get("code", 0) != 0:
                    raise ValueError("feishu profile request failed")
                profile_data = profile_payload.get("data")
                if not isinstance(profile_data, dict):
                    raise ValueError("feishu profile is invalid")

                open_id = self._required_text(profile_data, "open_id")
                tenant_key = self._required_text(profile_data, "tenant_key")
                display_name = self._required_text(profile_data, "name")
                avatar_url = profile_data.get("avatar_url")
                if not isinstance(avatar_url, str) or not avatar_url:
                    avatar_url = None
                phone = self._normalize_mainland_phone(
                    self._required_text(profile_data, "mobile")
                )
                return FeishuProfile(
                    subject=f"{tenant_key}:{open_id}",
                    display_name=display_name,
                    avatar_url=avatar_url,
                    phone=phone,
                )
        except (httpx.HTTPError, TypeError, ValueError) as error:
            raise ExternalIdentityUnavailable(
                "feishu identity is unavailable"
            ) from error

    @staticmethod
    def _required_text(payload: object, key: str) -> str:
        if not isinstance(payload, dict):
            raise ValueError("feishu response is invalid")
        value = payload.get(key)
        if not isinstance(value, str) or not value:
            raise ValueError("feishu response is invalid")
        return value

    @staticmethod
    def _normalize_mainland_phone(value: str) -> str:
        digits = re.sub(r"\D", "", value)
        if digits.startswith("86") and len(digits) == 13:
            digits = digits[2:]
        if re.fullmatch(r"1\d{10}", digits) is None:
            raise ValueError("feishu phone is invalid")
        return digits


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
