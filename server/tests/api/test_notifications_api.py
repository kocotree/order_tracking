from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import AuditLog, Factory, Notification, User
from app.main import create_app
from app.modules.identity_access import IdentityAccessService
from app.modules.notifications_audit import NotificationsAuditService


def test_notification_and_audit_http_contract_enforces_terminal_owner_csrf_and_redaction(
    test_database_engine: Engine,
    test_database_url: str,
) -> None:
    sessions = sessionmaker(test_database_engine, class_=Session, expire_on_commit=False)
    with sessions() as session, session.begin():
        session.add(
            Factory(
                factory_id="notification-api-factory",
                supplier_number="S11API",
                factory_name="通知接口工厂",
                factory_code="S11API",
                is_enabled=True,
            )
        )
        session.flush()
        session.add_all(
            [
                User(
                    user_id="notification-api-admin",
                    role="admin",
                    is_enabled=True,
                    feishu_display_name="通知管理员",
                ),
                User(
                    user_id="notification-api-admin-2",
                    role="admin",
                    is_enabled=True,
                    feishu_display_name="另一管理员",
                ),
                User(
                    user_id="notification-api-factory-user",
                    role="factory",
                    is_enabled=True,
                    feishu_display_name="通知工厂用户",
                    factory_id="notification-api-factory",
                    factory_position="employee",
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                Notification(
                    recipient_id="notification-api-admin",
                    category="SHIPMENT",
                    event_type="shipment.submitted",
                    target_type="shipment",
                    target_id="shipment-api-1",
                    title="工厂已提交发货",
                    summary="发货单 FH20260827-001 已形成正式记录",
                    target_path="/shipments/shipment-api-1",
                    dedupe_key="api-admin-notification",
                    created_at=datetime(2026, 8, 27, 9, 0),
                ),
                Notification(
                    recipient_id="notification-api-admin-2",
                    category="SHIPMENT",
                    event_type="shipment.submitted",
                    target_type="shipment",
                    target_id="shipment-api-2",
                    title="另一人的通知",
                    summary="不得被读取",
                    target_path="/shipments/shipment-api-2",
                    dedupe_key="api-other-notification",
                    created_at=datetime(2026, 8, 27, 9, 1),
                ),
                Notification(
                    recipient_id="notification-api-factory-user",
                    category="NEW_ORDER",
                    event_type="order_published",
                    target_type="factory_task",
                    target_id="order-api-1",
                    title="新订单任务",
                    summary="订单 S11-API 已发布",
                    target_path=(
                        "/pages/factory-task-detail/factory-task-detail?orderId=order-api-1"
                    ),
                    dedupe_key="api-factory-notification",
                    created_at=datetime(2026, 8, 27, 9, 2),
                ),
                AuditLog(
                    request_id="notification-audit-request",
                    action="shipment_submitted",
                    target_type="shipment",
                    target_id="shipment-api-1",
                    changes={"quantity": 10, "accessToken": "must-not-leak"},
                    actor_id="notification-api-factory-user",
                    source_terminal="factory-mini",
                    created_at=datetime(2026, 8, 27, 9, 0),
                ),
            ]
        )

    identity = IdentityAccessService(
        sessions,
        token_secret=b"notification-api-token-secret",
        phone_encryption_secret=b"notification-api-phone-secret",
        phone_digest_secret=b"notification-api-digest-secret",
    )
    admin_web = identity.issue_session(user_id="notification-api-admin", terminal="web")
    factory_mini = identity.issue_session(
        user_id="notification-api-factory-user", terminal="mini"
    )
    notifications = NotificationsAuditService(sessions)
    app = create_app(
        database_url=test_database_url,
        identity_service=identity,
        notifications_audit_service=notifications,
    )

    with TestClient(app, base_url="https://testserver") as anonymous:
        assert anonymous.get("/api/v1/admin/notifications").status_code == 401

    with TestClient(app, base_url="https://testserver") as admin:
        admin.cookies.set("ot_web_session", admin_web.access_token)
        admin.cookies.set("ot_csrf", admin_web.csrf_token or "")
        listed = admin.get("/api/v1/admin/notifications?page=1&pageSize=10")
        assert listed.status_code == 200
        assert listed.json()["total"] == 1
        notification_id = listed.json()["items"][0]["notificationId"]
        assert admin.get("/api/v1/admin/notifications/unread-count").json()["count"] == 1
        assert (
            admin.post(f"/api/v1/admin/notifications/{notification_id}/read").status_code
            == 403
        )
        marked = admin.post(
            f"/api/v1/admin/notifications/{notification_id}/read",
            headers={"X-CSRF-Token": admin_web.csrf_token or ""},
        )
        assert marked.status_code == 200
        assert marked.json()["readAt"] is not None
        assert admin.get("/api/v1/admin/notifications/unread-count").json()["count"] == 0

        audit = admin.get(
            "/api/v1/admin/audit-logs?targetType=shipment&sourceTerminal=factory-mini"
        )
        assert audit.status_code == 200
        assert audit.json()["total"] == 1
        assert audit.json()["items"][0]["changes"] == {"quantity": 10}

    with TestClient(app, base_url="https://testserver") as factory:
        factory.headers["Authorization"] = f"Bearer {factory_mini.access_token}"
        listed = factory.get("/api/v1/mini/notifications?status=all&page=1&pageSize=10")
        assert listed.status_code == 200
        assert listed.json()["total"] == 1
        own_id = listed.json()["items"][0]["notificationId"]
        assert (
            factory.post(
                f"/api/v1/mini/notifications/{notification_id}/read"
            ).status_code
            == 404
        )
        assert factory.post(f"/api/v1/mini/notifications/{own_id}/read").status_code == 200
        authorized = factory.post(
            "/api/v1/mini/notification-authorizations",
            json={
                "results": {
                    "factory_status": "accepted",
                    "factory_due": "closed",
                    "factory_repair": "rejected",
                }
            },
        )
        assert authorized.status_code == 201
        invalid_role_template = factory.post(
            "/api/v1/mini/notification-authorizations",
            json={"results": {"admin_shipment": "accepted"}},
        )
        assert invalid_role_template.status_code == 422
        assert factory.get("/api/v1/admin/audit-logs").status_code == 401
