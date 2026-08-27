from dataclasses import dataclass
from typing import Protocol


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
