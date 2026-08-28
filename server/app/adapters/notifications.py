from dataclasses import dataclass
from hashlib import sha256
from threading import Lock
from time import monotonic
from typing import Literal, Protocol

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import ExternalIdentity


@dataclass(frozen=True)
class DeliveryRequest:
    delivery_id: int
    recipient_id: str
    channel: str
    template_key: str
    title: str
    summary: str
    target_type: str
    target_id: str
    target_path: str
    template_data: dict[str, str]


@dataclass(frozen=True)
class OpsAlert:
    delivery_id: int
    channel: str
    error_code: str
    error_summary: str


class NotificationDeliveryError(RuntimeError):
    def __init__(
        self, code: str, *, retryable: bool, safe_summary: str = "外部通知发送失败"
    ) -> None:
        super().__init__(safe_summary)
        self.code = code
        self.retryable = retryable
        self.safe_summary = safe_summary


class WechatNotifier(Protocol):
    def send(self, request: DeliveryRequest) -> None: ...


class FeishuBusinessNotifier(Protocol):
    def send(self, request: DeliveryRequest) -> None: ...


class OpsAlertNotifier(Protocol):
    def send(self, alert: OpsAlert) -> None: ...


@dataclass(frozen=True)
class WechatSubscriptionConfig:
    app_id: str
    app_secret: str
    template_ids: dict[str, str]
    identity_scope: str = ""
    miniprogram_state: Literal["developer", "trial", "formal"] = "formal"
    access_token_url: str = "https://api.weixin.qq.com/cgi-bin/token"
    send_url: str = "https://api.weixin.qq.com/cgi-bin/message/subscribe/send"

    @property
    def resolved_identity_scope(self) -> str:
        if self.identity_scope:
            return self.identity_scope
        app_digest = sha256(self.app_id.encode()).hexdigest()[:32]
        return f"wechat-app/{app_digest}"


class AppCredentialWechatNotifier:
    def __init__(
        self,
        config: WechatSubscriptionConfig,
        session_factory: sessionmaker[Session],
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._config = config
        self._session_factory = session_factory
        self._transport = transport
        self._access_token: str | None = None
        self._access_token_expires_at = 0.0
        self._access_token_lock = Lock()

    def send(self, request: DeliveryRequest) -> None:
        template_id = self._config.template_ids.get(request.template_key, "").strip()
        if not template_id:
            raise NotificationDeliveryError(
                "wechat_template_not_configured",
                retryable=False,
                safe_summary="微信通知模板未配置",
            )
        openid = self._recipient_openid(request.recipient_id)
        if openid is None:
            raise NotificationDeliveryError(
                "wechat_recipient_unbound",
                retryable=False,
                safe_summary="接收人未绑定微信身份",
            )
        try:
            with httpx.Client(timeout=30, transport=self._transport) as client:
                access_token = self._server_access_token(client)
                response = client.post(
                    self._config.send_url,
                    params={"access_token": access_token},
                    json={
                        "touser": openid,
                        "template_id": template_id,
                        "page": request.target_path.removeprefix("/"),
                        "miniprogram_state": self._config.miniprogram_state,
                        "lang": "zh_CN",
                        "data": {
                            key: {"value": value}
                            for key, value in request.template_data.items()
                        },
                    },
                )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("wechat subscribe message send failed")
                errcode = payload.get("errcode")
                if errcode == 43101:
                    raise NotificationDeliveryError(
                        "wechat_subscription_not_available",
                        retryable=False,
                        safe_summary="微信订阅授权不可用",
                    )
                if errcode != 0:
                    raise ValueError("wechat subscribe message send failed")
        except NotificationDeliveryError:
            raise
        except (httpx.HTTPError, TypeError, ValueError) as error:
            raise NotificationDeliveryError(
                "wechat_delivery_unavailable",
                retryable=True,
                safe_summary="微信通知接口暂时不可用",
            ) from error

    def _recipient_openid(self, recipient_id: str) -> str | None:
        with self._session_factory() as session:
            return session.scalar(
                select(ExternalIdentity.platform_subject).where(
                    ExternalIdentity.platform == "wechat",
                    ExternalIdentity.scope == self._config.resolved_identity_scope,
                    ExternalIdentity.user_id == recipient_id,
                )
            )

    def _server_access_token(self, client: httpx.Client) -> str:
        with self._access_token_lock:
            now = monotonic()
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
            access_token = payload.get("access_token")
            expires_in = payload.get("expires_in")
            if (
                not isinstance(access_token, str)
                or not access_token
                or isinstance(expires_in, bool)
                or not isinstance(expires_in, (int, float))
                or expires_in <= 0
            ):
                raise ValueError("wechat access token response is invalid")
            self._access_token = access_token
            self._access_token_expires_at = now + max(0, float(expires_in) - 300)
            return access_token


class FakeWechatNotifier:
    def __init__(self) -> None:
        self.sent: list[DeliveryRequest] = []

    def send(self, request: DeliveryRequest) -> None:
        self.sent.append(request)


class FakeFeishuBusinessNotifier:
    def __init__(self) -> None:
        self.sent: list[DeliveryRequest] = []

    def send(self, request: DeliveryRequest) -> None:
        self.sent.append(request)


class FakeOpsAlertNotifier:
    def __init__(self) -> None:
        self.sent: list[OpsAlert] = []

    def send(self, alert: OpsAlert) -> None:
        self.sent.append(alert)


class DisabledWechatNotifier:
    def send(self, _request: DeliveryRequest) -> None:
        raise NotificationDeliveryError(
            "wechat_not_configured", retryable=False, safe_summary="微信通知渠道未配置"
        )


class DisabledFeishuBusinessNotifier:
    def send(self, _request: DeliveryRequest) -> None:
        raise NotificationDeliveryError(
            "feishu_not_configured", retryable=False, safe_summary="飞书业务通知渠道未配置"
        )


class DisabledOpsAlertNotifier:
    def send(self, _alert: OpsAlert) -> None:
        raise NotificationDeliveryError(
            "ops_alert_not_configured", retryable=False, safe_summary="运维告警渠道未配置"
        )
