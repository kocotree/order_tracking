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
        assert request.headers["authorization"] == "Bearer tenant-token"
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
            card_rows=(
                {
                    "orderNo": "E81",
                    "productName": "儿童遮阳帽",
                    "factoryNames": "通知工厂甲、通知工厂乙",
                    "contractShipDate": "2026-09-10",
                },
            ),
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
    assert business_payload["msg_type"] == "interactive"
    card = json.loads(business_payload["content"])
    assert card["schema"] == "2.0"
    assert card["header"] == {
        "template": "orange",
        "title": {"tag": "plain_text", "content": "合同出货提醒"},
    }
    assert card["body"]["elements"] == [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": "订单 E81 距合同出货时间还有 3 天",
            },
        },
        {
            "tag": "table",
            "page_size": 10,
            "row_height": "high",
            "freeze_first_column": True,
            "header_style": {"bold": True, "background_style": "grey"},
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
            "rows": [
                {
                    "orderNo": "E81",
                    "productName": "儿童遮阳帽",
                    "factoryNames": "通知工厂甲、通知工厂乙",
                    "contractShipDate": "2026-09-10",
                }
            ],
        },
        {
            "tag": "button",
            "text": {"tag": "plain_text", "content": "查看订单详情"},
            "type": "primary",
            "width": "fill",
            "behaviors": [
                {
                    "type": "open_url",
                    "default_url": "https://order-test.example.test/orders/order-1",
                }
            ],
        },
    ]
    ops_payload = json.loads(message_requests[1].content)
    assert ops_payload["receive_id"] == "ops-open-id"
    assert ops_payload["msg_type"] == "text"
    assert "delivery_id=2" in json.loads(ops_payload["content"])["text"]
    assert "wechat_delivery_unavailable" in json.loads(ops_payload["content"])["text"]


def test_admin_business_cards_have_event_fields_and_web_detail_links(
    test_database_engine: Engine,
) -> None:
    sessions = sessionmaker(test_database_engine, class_=Session, expire_on_commit=False)
    with sessions() as session, session.begin():
        session.add(
            User(
                user_id="card-user",
                role="admin",
                is_enabled=True,
                feishu_display_name="王心玲&煎饼",
            )
        )
        session.flush()
        session.add(
            ExternalIdentity(
                platform="feishu",
                scope="card-scope",
                platform_subject="tenant:recipient",
                user_id="card-user",
            )
        )
    cards = []

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("tenant_access_token/internal"):
            return httpx.Response(
                200, json={"code": 0, "tenant_access_token": "test", "expire": 7200}
            )
        body = json.loads(request.content)
        assert body["receive_id"] == "recipient"
        cards.append(json.loads(body["content"]))
        return httpx.Response(200, json={"code": 0})

    notifier = AppCredentialFeishuBusinessNotifier(
        FeishuNotificationConfig(
            app_id="test",
            app_secret="test",
            identity_scope="card-scope",
            admin_web_base_url="https://admin.example.test",
            ops_alert_recipient_user_id="",
        ),
        sessions,
        transport=httpx.MockTransport(respond),
    )
    cases = [
        (
            "admin_shipment",
            "shipment",
            "/shipments/sh-1",
            {"totalQuantity": "12"},
            (
                {
                    "orderNo": "E81",
                    "productName": "帽子",
                    "propertiesValue": "蓝色",
                    "quantity": "12",
                },
            ),
            ["订单编号", "商品名称", "颜色规格", "发货数量"],
            "查看发货单",
        ),
        (
            "admin_repair",
            "repair",
            "/repairs/re-1",
            {},
            (
                {
                    "factoryName": "甲厂",
                    "repairedQuantity": "5",
                    "scrappedQuantity": "2",
                    "returnedQuantity": "7",
                },
            ),
            ["工厂", "返修数量", "报废数量", "返回总数量"],
            "查看返修详情",
        ),
        (
            "admin_void_request",
            "shipment",
            "/shipments/sh-1",
            {
                "factoryName": "甲厂",
                "shipmentNo": "FH01",
                "applicant": "员工",
                "requestedAt": "2026-09-05 12:00",
                "reason": "数量错误",
            },
            (),
            [],
            "查看并处理",
        ),
    ]
    for key, target_type, path, data, rows, labels, button in cases:
        notifier.send(
            DeliveryRequest(
                delivery_id=1,
                recipient_id="card-user",
                channel="feishu",
                template_key=key,
                title="业务通知",
                summary="说明",
                target_type=target_type,
                target_id="target",
                target_path=path,
                template_data=data,
                card_rows=rows,
            )
        )
        elements = cards[-1]["body"]["elements"]
        tables = [e for e in elements if e["tag"] == "table"]
        if labels:
            assert [c["display_name"] for c in tables[0]["columns"]] == labels
            assert tables[0]["rows"] == list(rows)
        else:
            assert tables == []
            for value in data.values():
                assert value in json.dumps(elements, ensure_ascii=False)
        assert elements[-1]["text"]["content"] == button
        assert elements[-1]["behaviors"][0]["default_url"] == "https://admin.example.test" + path
        if key == "admin_shipment":
            assert "发货总数量：12" in json.dumps(elements, ensure_ascii=False)
        if key == "admin_repair":
            assert "本次发回" in json.dumps(elements, ensure_ascii=False)


def test_business_card_missing_app_identity_fails_without_using_other_app_open_id(
    test_database_engine: Engine,
) -> None:
    import pytest

    from app.adapters.notifications import NotificationDeliveryError

    sessions = sessionmaker(test_database_engine, class_=Session, expire_on_commit=False)
    with sessions() as session, session.begin():
        session.add(
            User(
                user_id="missing", role="admin", is_enabled=True, feishu_display_name="王心玲&煎饼"
            )
        )
        session.flush()
        session.add(
            ExternalIdentity(
                platform="feishu",
                scope="other-cli-app",
                platform_subject="tenant:other-openid",
                user_id="missing",
            )
        )

    def respond(request: httpx.Request) -> httpx.Response:
        raise AssertionError("Unbound recipient must not contact Feishu")

    notifier = AppCredentialFeishuBusinessNotifier(
        FeishuNotificationConfig(
            app_id="test",
            app_secret="test",
            identity_scope="business-app",
            admin_web_base_url="https://admin.example.test",
            ops_alert_recipient_user_id="",
        ),
        sessions,
        transport=httpx.MockTransport(respond),
    )
    with pytest.raises(NotificationDeliveryError) as error:
        notifier.send(
            DeliveryRequest(
                delivery_id=1,
                recipient_id="missing",
                channel="feishu",
                template_key="admin_shipment",
                title="通知",
                summary="说明",
                target_type="shipment",
                target_id="sh-1",
                target_path="/shipments/sh-1",
                template_data={"totalQuantity": "12"},
            )
        )
    assert error.value.code == "feishu_recipient_unbound"
    assert error.value.retryable is False
