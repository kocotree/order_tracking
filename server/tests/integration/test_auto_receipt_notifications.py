from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.notifications import FakeWechatNotifier
from app.db.models import OutboxMessage, QuantityLedger
from app.modules.notifications_audit import NotificationsAuditService
from tests.api.test_shipment_api import USER_IDS
from tests.api.test_shipment_receipt_api import receipt_clients as receipt_clients


def test_delayed_notifications_keep_each_save_difference(receipt_clients, test_database_engine):
    admin, _, sid = receipt_clients
    url = f"/api/v1/admin/shipments/{sid}/receipt"
    receipt = admin.get(url).json()
    for version, quantity in [(1, 5), (2, 8)]:
        receipt["items"][0]["quantity"] = quantity
        response = admin.put(url, json={"version": version, "items": receipt["items"]},
                             headers={"Idempotency-Key": f"save-{version}"})
        assert response.status_code == 200, response.text
    service = NotificationsAuditService(sessionmaker(test_database_engine, expire_on_commit=False))
    while service.consume_next_business_event(worker_id="delayed"):
        pass
    messages = service.list_notifications(user_id=USER_IDS[0], unread_only=False,
                                          page=1, page_size=10)
    assert messages.total == 2
    assert "增加3件" in messages.items[0].summary
    assert "减少5件" in messages.items[1].summary


def test_net_zero_box_change_still_audits_and_notifies_without_zero_ledger(
    receipt_clients, test_database_engine,
):
    admin, _, sid = receipt_clients
    url = f"/api/v1/admin/shipments/{sid}/receipt"
    receipt = admin.get(url).json()
    with Session(test_database_engine) as session:
        count = session.scalar(select(func.count()).select_from(QuantityLedger))
    receipt["items"][0]["quantity"], receipt["items"][1]["quantity"] = 20, 10
    response = admin.put(url, json={"version": 1, "items": receipt["items"]})
    assert response.status_code == 200, response.text
    assert response.json()["version"] == 2
    operations = admin.get(f"/api/v1/admin/shipments/{sid}").json()["operations"]
    assert operations[0]["action"] == "shipment_submitted"
    assert any(entry["action"] == "shipment_receipt_saved" for entry in operations)
    with Session(test_database_engine) as session:
        assert session.scalar(select(func.count()).select_from(QuantityLedger)) == count
        assert session.scalar(select(OutboxMessage).where(
            OutboxMessage.event_type == "shipment.receipt_adjusted",
        )).payload["differences"] == []


def test_old_receipt_events_and_retried_deliveries_never_send(
    receipt_clients, test_database_engine,
):
    _, _, sid = receipt_clients
    now = datetime.now(UTC)
    with Session(test_database_engine) as session, session.begin():
        event = OutboxMessage(
            event_type="shipment.receipt_confirmed", aggregate_type="shipment",
            aggregate_id=sid, dedupe_key="retired-business", payload={}, available_at=now,
        )
        session.add(event)
        session.flush()
        session.add(OutboxMessage(
            event_type="notification.delivery", aggregate_type="shipment", aggregate_id=sid,
            dedupe_key="retired-delivery", payload={}, source_event_id=event.id,
            message_kind="delivery", channel="wechat", recipient_id=USER_IDS[0],
            available_at=now, attempts=2,
        ))
    service = NotificationsAuditService(sessionmaker(test_database_engine, expire_on_commit=False))
    while service.consume_next_business_event(worker_id="retired"):
        pass
    notifier = FakeWechatNotifier()
    assert service.deliver_next(worker_id="retired", wechat_notifier=notifier)
    assert notifier.sent == []
    with Session(test_database_engine) as session:
        old = session.scalars(select(OutboxMessage).where(
            OutboxMessage.dedupe_key.in_(["retired-business", "retired-delivery"]),
        )).all()
        assert all(row.status == "completed" for row in old)
        assert all(row.last_error_code == "receipt_notification_retired" for row in old)
