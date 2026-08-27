import re
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from threading import Lock
from time import monotonic
from typing import Protocol

import httpx

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


@dataclass(frozen=True)
class WechatIdentityConfig:
    app_id: str
    app_secret: str
    code_session_url: str = "https://api.weixin.qq.com/sns/jscode2session"
    access_token_url: str = "https://api.weixin.qq.com/cgi-bin/token"
    phone_number_url: str = (
        "https://api.weixin.qq.com/wxa/business/getuserphonenumber"
    )


class AppCredentialWechatIdentity:
    def __init__(
        self,
        config: WechatIdentityConfig,
        *,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._config = config
        self._transport = transport
        self._clock = clock
        self._access_token: str | None = None
        self._access_token_expires_at = 0.0
        self._access_token_lock = Lock()
        app_digest = sha256(config.app_id.encode()).hexdigest()[:32]
        self._scope = f"wechat-app/{app_digest}"

    @property
    def scope(self) -> str:
        return self._scope

    def exchange_login_code(self, *, code: str) -> WechatProfile:
        try:
            with httpx.Client(timeout=30, transport=self._transport) as client:
                response = client.get(
                    self._config.code_session_url,
                    params={
                        "appid": self._config.app_id,
                        "secret": self._config.app_secret,
                        "js_code": code,
                        "grant_type": "authorization_code",
                    },
                )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict) or payload.get("errcode", 0) != 0:
                    raise ValueError("wechat login exchange failed")
                openid = self._required_text(payload, "openid")
                self._required_text(payload, "session_key")
                return WechatProfile(subject=openid)
        except (httpx.HTTPError, TypeError, ValueError) as error:
            raise WechatUnavailable("wechat identity is unavailable") from error

    def exchange_phone_code(self, *, code: str) -> str:
        try:
            with httpx.Client(timeout=30, transport=self._transport) as client:
                access_token = self._server_access_token(client)

                phone_response = client.post(
                    self._config.phone_number_url,
                    params={"access_token": access_token},
                    json={"code": code},
                )
                phone_response.raise_for_status()
                phone_payload = phone_response.json()
                if not isinstance(phone_payload, dict) or phone_payload.get("errcode", 0) != 0:
                    raise ValueError("wechat phone exchange failed")
                phone_info = phone_payload.get("phone_info")
                if not isinstance(phone_info, dict):
                    raise ValueError("wechat phone response is invalid")
                phone = phone_info.get("purePhoneNumber")
                if not isinstance(phone, str) or not phone:
                    phone = self._required_text(phone_info, "phoneNumber")
                return self._normalize_mainland_phone(phone)
        except (httpx.HTTPError, TypeError, ValueError) as error:
            raise WechatUnavailable("wechat phone is unavailable") from error

    def _server_access_token(self, client: httpx.Client) -> str:
        with self._access_token_lock:
            now = self._clock()
            if self._access_token is not None and now < self._access_token_expires_at:
                return self._access_token
            response = client.get(
                self._config.access_token_url,
                params={
                    "grant_type": "client_credential",
                    "appid": self._config.app_id,
                    "secret": self._config.app_secret,
                },
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or payload.get("errcode", 0) != 0:
                raise ValueError("wechat access token exchange failed")
            access_token = self._required_text(payload, "access_token")
            expires_in = payload.get("expires_in")
            if isinstance(expires_in, bool) or not isinstance(expires_in, (int, float)):
                raise ValueError("wechat access token response is invalid")
            if expires_in <= 0:
                raise ValueError("wechat access token response is invalid")
            self._access_token = access_token
            self._access_token_expires_at = now + max(0, float(expires_in) - 300)
            return access_token

    @staticmethod
    def _required_text(payload: object, key: str) -> str:
        if not isinstance(payload, dict):
            raise ValueError("wechat response is invalid")
        value = payload.get(key)
        if not isinstance(value, str) or not value:
            raise ValueError("wechat response is invalid")
        return value

    @staticmethod
    def _normalize_mainland_phone(value: str) -> str:
        digits = re.sub(r"\D", "", value)
        if digits.startswith("86") and len(digits) == 13:
            digits = digits[2:]
        if re.fullmatch(r"1\d{10}", digits) is None:
            raise ValueError("wechat phone is invalid")
        return digits


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
