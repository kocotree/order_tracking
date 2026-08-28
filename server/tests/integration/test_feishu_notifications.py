import json

import httpx
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.notifications import (
    AppCredentialFeishuBusinessNotifier,
    AppCredentialOpsAlertNotifier,
    DeliveryRequest,
    FeishuNotificationConfig,
    OpsAlert,
)
from app.db.models import ExternalIdentity, User


def test_real_feishu_adapters_send_business_message_and_ops_alert(
    test_database_engine: Engine,
) -> None:
    sessions = sessionmaker(test_database_engine, class_=Session, expire_on_commit=False)
    with sessions() as session, session.begin():
        session.add_all(
            [
                User(
                    user_id="tracker-user",
                    role="admin",
                    is_enabled=True,
                    feishu_display_name="跟单人员",
                ),
                User(
                    user_id="ops-user",
                    role="admin",
                    is_enabled=True,
                    feishu_display_name="煎饼",
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                ExternalIdentity(
                    platform="feishu",
                    scope="feishu-app/test-scope",
                    platform_subject="tenant-key:tracker-open-id",
                    user_id="tracker-user",
                ),
                ExternalIdentity(
                    platform="feishu",
                    scope="feishu-app/test-scope",
                    platform_subject="tenant-key:ops-open-id",
                    user_id="ops-user",
                ),
            ]
        )

    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("tenant_access_token/internal"):
            return httpx.Response(
                200,
                json={"code": 0, "tenant_access_token": "tenant-token", "expire": 7200},
            )
        payload = json.loads(request.content)
        assert request.headers["authorization"] == "Bearer tenant-token"
        assert payload["msg_type"] == "text"
        return httpx.Response(200, json={"code": 0, "msg": "success"})

    config = FeishuNotificationConfig(
        app_id="feishu-app-id",
        app_secret="feishu-app-secret",
        identity_scope="feishu-app/test-scope",
        admin_web_base_url="https://order-test.example.test",
        ops_alert_recipient_user_id="ops-user",
    )
    transport = httpx.MockTransport(respond)
    business = AppCredentialFeishuBusinessNotifier(
        config, sessions, transport=transport
    )
    ops = AppCredentialOpsAlertNotifier(config, sessions, transport=transport)

    business.send(
        DeliveryRequest(
            delivery_id=1,
            recipient_id="tracker-user",
            channel="feishu",
            template_key="due_d3",
            title="合同出货提醒",
            summary="订单 E81 距合同出货时间还有 3 天",
            target_type="order",
            target_id="order-1",
            target_path="/orders/order-1",
            template_data={},
        )
    )
    ops.send(
        OpsAlert(
            delivery_id=2,
            channel="wechat",
            error_code="wechat_delivery_unavailable",
            error_summary="微信通知接口暂时不可用",
        )
    )

    message_requests = [
        request for request in requests if request.url.path.endswith("/im/v1/messages")
    ]
    assert len(message_requests) == 2
    business_payload = json.loads(message_requests[0].content)
    assert message_requests[0].url.params["receive_id_type"] == "open_id"
    assert business_payload["receive_id"] == "tracker-open-id"
    assert json.loads(business_payload["content"])["text"] == (
        "合同出货提醒\n订单 E81 距合同出货时间还有 3 天\n"
        "https://order-test.example.test/orders/order-1"
    )
    ops_payload = json.loads(message_requests[1].content)
    assert ops_payload["receive_id"] == "ops-open-id"
    assert "delivery_id=2" in json.loads(ops_payload["content"])["text"]
    assert "wechat_delivery_unavailable" in json.loads(ops_payload["content"])["text"]
