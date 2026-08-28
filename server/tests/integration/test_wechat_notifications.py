from urllib.parse import parse_qs

import httpx
import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.notifications import (
    AppCredentialWechatNotifier,
    DeliveryRequest,
    NotificationDeliveryError,
    WechatSubscriptionConfig,
)
from app.db.models import ExternalIdentity, User


def test_real_wechat_adapter_sends_selected_template_to_bound_recipient(
    test_database_engine: Engine,
) -> None:
    sessions = sessionmaker(test_database_engine, class_=Session, expire_on_commit=False)
    with sessions() as session, session.begin():
        session.add(
            User(
                user_id="factory-wechat-user",
                role="factory",
                is_enabled=True,
                feishu_display_name="微信通知工厂用户",
            )
        )
        session.flush()
        session.add(
            ExternalIdentity(
                platform="wechat",
                scope="wechat-app/test-scope",
                platform_subject="test-openid",
                user_id="factory-wechat-user",
            )
        )

    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/cgi-bin/token":
            assert request.method == "GET"
            assert parse_qs(request.url.query.decode()) == {
                "grant_type": ["client_credential"],
                "appid": ["wx-test-app"],
                "secret": ["test-app-secret"],
            }
            return httpx.Response(
                200,
                json={"access_token": "server-access-token", "expires_in": 7200},
            )

        assert request.method == "POST"
        assert request.url == httpx.URL(
            "https://api.weixin.qq.com/cgi-bin/message/subscribe/send"
            "?access_token=server-access-token"
        )
        assert request.read().decode() == (
            '{"touser":"test-openid",'
            '"template_id":"template-status",'
            '"page":"pages/factory-task-detail/factory-task-detail?orderId=order-1",'
            '"miniprogram_state":"trial","lang":"zh_CN",'
            '"data":{"thing1":{"value":"跟单管理系统"},'
            '"character_string2":{"value":"S11-001"},'
            '"phrase3":{"value":"新订单"},'
            '"time4":{"value":"2026-08-28 09:30"}}}'
        )
        return httpx.Response(200, json={"errcode": 0, "errmsg": "ok"})

    notifier = AppCredentialWechatNotifier(
        WechatSubscriptionConfig(
            app_id="wx-test-app",
            app_secret="test-app-secret",
            identity_scope="wechat-app/test-scope",
            template_ids={"factory_status": "template-status"},
            miniprogram_state="trial",
        ),
        sessions,
        transport=httpx.MockTransport(respond),
    )

    notifier.send(
        DeliveryRequest(
            delivery_id=1,
            recipient_id="factory-wechat-user",
            channel="wechat",
            template_key="factory_status",
            title="新订单任务",
            summary="订单 S11-001 已发布",
            target_type="factory_task",
            target_id="order-1",
            target_path=(
                "/pages/factory-task-detail/factory-task-detail?orderId=order-1"
            ),
            template_data={
                "thing1": "跟单管理系统",
                "character_string2": "S11-001",
                "phrase3": "新订单",
                "time4": "2026-08-28 09:30",
            },
        )
    )

    assert len(requests) == 2


def test_real_wechat_adapter_treats_missing_subscription_grant_as_terminal(
    test_database_engine: Engine,
) -> None:
    sessions = sessionmaker(test_database_engine, class_=Session, expire_on_commit=False)
    with sessions() as session, session.begin():
        session.add(
            User(
                user_id="factory-refused-user",
                role="factory",
                is_enabled=True,
                feishu_display_name="拒绝订阅用户",
            )
        )
        session.flush()
        session.add(
            ExternalIdentity(
                platform="wechat",
                scope="wechat-app/test-scope",
                platform_subject="refused-openid",
                user_id="factory-refused-user",
            )
        )

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/cgi-bin/token":
            return httpx.Response(
                200,
                json={"access_token": "server-access-token", "expires_in": 7200},
            )
        return httpx.Response(
            200,
            json={"errcode": 43101, "errmsg": "user refuse to accept the msg"},
        )

    notifier = AppCredentialWechatNotifier(
        WechatSubscriptionConfig(
            app_id="wx-test-app",
            app_secret="test-app-secret",
            identity_scope="wechat-app/test-scope",
            template_ids={"factory_status": "template-status"},
            miniprogram_state="trial",
        ),
        sessions,
        transport=httpx.MockTransport(respond),
    )

    with pytest.raises(NotificationDeliveryError) as captured:
        notifier.send(
            DeliveryRequest(
                delivery_id=2,
                recipient_id="factory-refused-user",
                channel="wechat",
                template_key="factory_status",
                title="新订单任务",
                summary="订单 S11-002 已发布",
                target_type="factory_task",
                target_id="order-2",
                target_path="/pages/factory-tasks/factory-tasks",
                template_data={"phrase3": "新订单"},
            )
        )

    assert captured.value.code == "wechat_subscription_not_available"
    assert captured.value.retryable is False
    assert str(captured.value) == "微信订阅授权不可用"
