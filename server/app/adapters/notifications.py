import json
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
    card_rows: tuple[dict[str, str], ...] = ()


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


@dataclass(frozen=True)
class FeishuNotificationConfig:
    app_id: str
    app_secret: str
    admin_web_base_url: str
    ops_alert_recipient_user_id: str
    identity_scope: str = ""
    base_url: str = "https://open.feishu.cn"

    @property
    def resolved_identity_scope(self) -> str:
        if self.identity_scope:
            return self.identity_scope
        app_digest = sha256(self.app_id.encode()).hexdigest()[:32]
        return f"feishu-app/{app_digest}"


class _AppCredentialFeishuSender:
    def __init__(
        self,
        config: FeishuNotificationConfig,
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

    def send_text(self, *, recipient_id: str, text: str) -> None:
        self._send_message(
            recipient_id=recipient_id,
            msg_type="text",
            content={"text": text},
        )

    def send_card(self, *, recipient_id: str, card: dict[str, object]) -> None:
        self._send_message(
            recipient_id=recipient_id,
            msg_type="interactive",
            content=card,
        )

    def _send_message(
        self,
        *,
        recipient_id: str,
        msg_type: str,
        content: dict[str, object],
    ) -> None:
        open_id = self._recipient_openid(recipient_id)
        if open_id is None:
            raise NotificationDeliveryError(
                "feishu_recipient_unbound",
                retryable=False,
                safe_summary="接收人未绑定飞书身份",
            )
        try:
            with httpx.Client(
                base_url=self._config.base_url,
                timeout=30,
                transport=self._transport,
            ) as client:
                token = self._tenant_access_token(client)
                response = client.post(
                    "/open-apis/im/v1/messages",
                    params={"receive_id_type": "open_id"},
                    headers={"Authorization": f"Bearer {token}"},
                    json={
                        "receive_id": open_id,
                        "msg_type": msg_type,
                        "content": json.dumps(content, ensure_ascii=False),
                    },
                )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict) or payload.get("code") != 0:
                    raise NotificationDeliveryError(
                        "feishu_delivery_rejected",
                        retryable=False,
                        safe_summary="飞书通知被平台拒绝",
                    )
        except NotificationDeliveryError:
            raise
        except httpx.HTTPStatusError as error:
            status_code = error.response.status_code
            raise NotificationDeliveryError(
                "feishu_delivery_unavailable",
                retryable=status_code == 429 or status_code >= 500,
                safe_summary="飞书通知接口暂时不可用",
            ) from error
        except (httpx.HTTPError, TypeError, ValueError) as error:
            raise NotificationDeliveryError(
                "feishu_delivery_unavailable",
                retryable=True,
                safe_summary="飞书通知接口暂时不可用",
            ) from error

    def _recipient_openid(self, recipient_id: str) -> str | None:
        with self._session_factory() as session:
            subject = session.scalar(
                select(ExternalIdentity.platform_subject).where(
                    ExternalIdentity.platform == "feishu",
                    ExternalIdentity.scope == self._config.resolved_identity_scope,
                    ExternalIdentity.user_id == recipient_id,
                )
            )
        if not isinstance(subject, str):
            return None
        _tenant, separator, open_id = subject.partition(":")
        return open_id if separator and open_id else subject

    def _tenant_access_token(self, client: httpx.Client) -> str:
        with self._access_token_lock:
            now = monotonic()
            if self._access_token is not None and now < self._access_token_expires_at:
                return self._access_token
            response = client.post(
                "/open-apis/auth/v3/tenant_access_token/internal",
                json={
                    "app_id": self._config.app_id,
                    "app_secret": self._config.app_secret,
                },
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or payload.get("code") != 0:
                raise ValueError("feishu tenant token exchange failed")
            access_token = payload.get("tenant_access_token")
            expires_in = payload.get("expire")
            if (
                not isinstance(access_token, str)
                or not access_token
                or isinstance(expires_in, bool)
                or not isinstance(expires_in, (int, float))
                or expires_in <= 0
            ):
                raise ValueError("feishu tenant token response is invalid")
            self._access_token = access_token
            self._access_token_expires_at = now + max(0, float(expires_in) - 300)
            return access_token


class AppCredentialFeishuBusinessNotifier:
    def __init__(
        self,
        config: FeishuNotificationConfig,
        session_factory: sessionmaker[Session],
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._config = config
        self._sender = _AppCredentialFeishuSender(
            config, session_factory, transport=transport
        )

    def send(self, request: DeliveryRequest) -> None:
        if request.template_key in {"admin_shipment", "admin_repair", "admin_void_request"}:
            self._send_admin_card(request)
            return
        target_url = f"{self._config.admin_web_base_url.rstrip('/')}{request.target_path}"
        self._sender.send_card(
            recipient_id=request.recipient_id,
            card={
                "schema": "2.0",
                "header": {
                    "template": "orange",
                    "title": {"tag": "plain_text", "content": request.title},
                },
                "body": {
                    "elements": [
                        {
                            "tag": "div",
                            "text": {
                                "tag": "lark_md",
                                "content": request.summary,
                            },
                        },
                        {
                            "tag": "table",
                            "page_size": 10,
                            "row_height": "high",
                            "freeze_first_column": True,
                            "header_style": {
                                "bold": True,
                                "background_style": "grey",
                            },
                            "columns": [
                                {
                                    "name": "orderNo",
                                    "display_name": "订单编号",
                                    "data_type": "text",
                                    "width": "auto",
                                },
                                {
                                    "name": "productName",
                                    "display_name": "商品名称",
                                    "data_type": "text",
                                    "width": "auto",
                                },
                                {
                                    "name": "factoryNames",
                                    "display_name": "生产工厂",
                                    "data_type": "text",
                                    "width": "auto",
                                },
                                {
                                    "name": "contractShipDate",
                                    "display_name": "合同出货时间",
                                    "data_type": "text",
                                    "width": "auto",
                                },
                            ],
                            "rows": list(request.card_rows),
                        },
                        {
                            "tag": "button",
                            "text": {
                                "tag": "plain_text",
                                "content": (
                                    "查看订单详情"
                                    if request.target_type == "order"
                                    else "查看订单列表"
                                ),
                            },
                            "type": "primary",
                            "width": "fill",
                            "behaviors": [
                                {
                                    "type": "open_url",
                                    "default_url": target_url,
                                }
                            ],
                        },
                    ]
                },
            },
        )

    def _send_admin_card(self, request: DeliveryRequest) -> None:
        elements: list[dict[str, object]] = [
            {"tag": "div", "text": {"tag": "plain_text", "content": request.summary}}
        ]
        columns: tuple[tuple[str, str], ...] = ()
        if request.template_key == "admin_shipment":
            columns = (
                ("orderNo", "订单编号"),
                ("productName", "商品名称"),
                ("propertiesValue", "颜色规格"),
                ("quantity", "发货数量"),
            )
            button = "查看发货单"
        elif request.template_key == "admin_repair":
            columns = (
                ("factoryName", "工厂"),
                ("repairedQuantity", "返修数量"),
                ("scrappedQuantity", "报废数量"),
                ("returnedQuantity", "返回总数量"),
            )
            elements.append({"tag": "div", "text": {"tag": "plain_text", "content": "本次发回"}})
            button = "查看返修详情"
        else:
            button = "查看并处理"
            for key, label in (
                ("factoryName", "工厂"),
                ("shipmentNo", "发货单号"),
                ("applicant", "申请人"),
                ("requestedAt", "申请时间"),
                ("reason", "申请原因"),
            ):
                elements.append(
                    {
                        "tag": "div",
                        "text": {
                            "tag": "plain_text",
                            "content": f"{label}：{request.template_data[key]}",
                        },
                    }
                )
        if columns:
            elements.append(
                {
                    "tag": "table",
                    "page_size": 10,
                    "row_height": "high",
                    "freeze_first_column": True,
                    "header_style": {"bold": True, "background_style": "grey"},
                    "columns": [
                        {"name": key, "display_name": label, "data_type": "text", "width": "auto"}
                        for key, label in columns
                    ],
                    "rows": list(request.card_rows),
                }
            )
        if request.template_key == "admin_shipment":
            elements.append(
                {
                    "tag": "div",
                    "text": {
                        "tag": "plain_text",
                        "content": f"发货总数量：{request.template_data['totalQuantity']}",
                    },
                }
            )
        elements.append(
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": button},
                "type": "primary",
                "width": "fill",
                "behaviors": [
                    {
                        "type": "open_url",
                        "default_url": (
                            f"{self._config.admin_web_base_url.rstrip('/')}"
                            f"{request.target_path}"
                        ),
                    }
                ],
            }
        )
        self._sender.send_card(
            recipient_id=request.recipient_id,
            card={
                "schema": "2.0",
                "header": {
                    "template": "orange",
                    "title": {"tag": "plain_text", "content": request.title},
                },
                "body": {"elements": elements},
            },
        )


class AppCredentialOpsAlertNotifier:
    def __init__(
        self,
        config: FeishuNotificationConfig,
        session_factory: sessionmaker[Session],
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._config = config
        self._sender = _AppCredentialFeishuSender(
            config, session_factory, transport=transport
        )

    def send(self, alert: OpsAlert) -> None:
        self._sender.send_text(
            recipient_id=self._config.ops_alert_recipient_user_id,
            text=(
                "跟单管理系统运维告警\n"
                f"delivery_id={alert.delivery_id}\n"
                f"channel={alert.channel}\n"
                f"error_code={alert.error_code}\n"
                f"{alert.error_summary}"
            ),
        )


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
