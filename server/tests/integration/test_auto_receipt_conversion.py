from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, event, func, select
from sqlalchemy.orm import Session

from app.db.models import (
    AuditLog,
    OutboxMessage,
    QuantityLedger,
    Shipment,
    ShipmentReceipt,
    ShipmentReceiptItem,
    ShipmentReturnEvent,
    ShipmentWritebackFact,
)
from scripts.convert_auto_receipts import convert
from tests.api.test_shipment_api import ADMIN_ID
from tests.api.test_shipment_receipt_api import receipt_clients as receipt_clients


def make_historical(engine, shipment_id, *, draft_quantity=None, resubmitted=False):
    with Session(engine) as session, session.begin():
        shipment = session.get(Shipment, shipment_id)
        shipment.first_submitted_at = None
        if draft_quantity is None:
            session.execute(delete(ShipmentReceiptItem))
            session.execute(delete(ShipmentReceipt))
        else:
            receipt = session.get(ShipmentReceipt, shipment_id)
            receipt.status = "DRAFT"
            receipt.saved_by = ADMIN_ID
            session.scalars(select(ShipmentReceiptItem)).first().quantity = draft_quantity
        if resubmitted:
            session.execute(delete(ShipmentWritebackFact))
            session.execute(delete(AuditLog))
            session.add(AuditLog(
                request_id="resubmitted", action="shipment_resubmitted", target_type="shipment",
                target_id=shipment_id, changes={}, created_at=shipment.submitted_at,
            ))


@pytest.mark.parametrize("draft_quantity", [None, 10])
def test_conversion_is_read_only_by_default_and_idempotent(
    receipt_clients, test_database_engine, draft_quantity,
):
    admin, factory, shipment_id = receipt_clients
    make_historical(test_database_engine, shipment_id, draft_quantity=draft_quantity)
    now = datetime.now(UTC)
    preview = convert(test_database_engine, now=now)
    assert preview["convert"] == [shipment_id]
    assert preview["errors"] == []
    with Session(test_database_engine) as session:
        assert session.get(Shipment, shipment_id).first_submitted_at is None
        assert session.scalar(select(func.count()).select_from(AuditLog).where(
            AuditLog.action == "shipment_receipt_converted",
        )) == 0
        ledger = session.scalar(select(func.count()).select_from(QuantityLedger))
        facts = session.scalar(select(func.count()).select_from(ShipmentWritebackFact))
    applied = convert(test_database_engine, expected_digest=preview["digest"], now=now)
    assert applied["applied"] is True
    detail = admin.get(f"/api/v1/admin/shipments/{shipment_id}").json()
    assert detail["receipt"]["status"] == "CONFIRMED"
    assert detail["receipt"]["confirmedByName"] is None
    assert detail["totalQuantity"] == 30
    assert factory.get("/api/v1/factory/shipment-catalog").json()["items"][0][
        "shippedQuantity"
    ] == 35
    again = convert(test_database_engine, now=now)
    assert again["convert"] == []
    convert(test_database_engine, expected_digest=again["digest"], now=now)
    with Session(test_database_engine) as session:
        assert session.scalar(select(func.count()).select_from(QuantityLedger)) == ledger
        assert session.scalar(select(func.count()).select_from(ShipmentWritebackFact)) == facts
        assert session.scalar(select(func.count()).select_from(AuditLog).where(
            AuditLog.action == "shipment_receipt_converted",
        )) == 1


@pytest.mark.parametrize("problem", [
    "draft", "missing_first", "future", "changed", "only_resubmit_fact", "conflicting_first",
])
def test_conversion_rejects_unresolved_drafts_or_unproven_times_without_partial_writes(
    receipt_clients, test_database_engine, problem,
):
    _, _, shipment_id = receipt_clients
    make_historical(test_database_engine, shipment_id,
                    draft_quantity=9 if problem == "draft" else None,
                    resubmitted=problem in ("missing_first", "only_resubmit_fact"))
    if problem == "only_resubmit_fact":
        with Session(test_database_engine) as session, session.begin():
            session.add(ShipmentWritebackFact(
                root_id=shipment_id, event_key=f"resubmit:{shipment_id}", status="SHIPPED",
                occurred_at=session.get(Shipment, shipment_id).submitted_at, lines=[],
            ))
    if problem == "conflicting_first":
        with Session(test_database_engine) as session, session.begin():
            shipment = session.get(Shipment, shipment_id)
            shipment.first_submitted_at = shipment.submitted_at - timedelta(days=1)
    if problem == "future":
        with Session(test_database_engine) as session, session.begin():
            session.get(Shipment, shipment_id).submitted_at = datetime.now(UTC) + timedelta(days=1)
    preview = convert(test_database_engine)
    if problem == "changed":
        with Session(test_database_engine) as session, session.begin():
            session.get(Shipment, shipment_id).version += 1
    else:
        assert preview["errors"]
    with pytest.raises(ValueError):
        convert(test_database_engine, expected_digest=preview["digest"])
    with Session(test_database_engine) as session:
        first = session.get(Shipment, shipment_id).first_submitted_at
        assert (first is not None) if problem == "conflicting_first" else (first is None)


def test_conversion_preserves_received_returns(
    receipt_clients, test_database_engine,
):
    admin, _, shipment_id = receipt_clients
    detail = admin.get(f"/api/v1/admin/shipments/{shipment_id}").json()
    returned = admin.post(f"/api/v1/admin/shipments/{shipment_id}/returns", json={
        "reason": "测试", "lines": [{"shipmentLineId": detail["lines"][0]["lineId"],
                                     "quantity": 1}],
    }, headers={"Idempotency-Key": "conversion-return"})
    assert returned.status_code == 201, returned.text
    detail_after_return = admin.get(f"/api/v1/admin/shipments/{shipment_id}").json()
    preview = convert(test_database_engine)
    assert preview["received"] == [shipment_id]
    assert preview["returns"] == [shipment_id]
    convert(test_database_engine, expected_digest=preview["digest"])
    assert admin.get(f"/api/v1/admin/shipments/{shipment_id}").json() == detail_after_return
    with Session(test_database_engine) as session:
        assert session.scalar(select(func.count()).select_from(ShipmentReturnEvent)) == 1


def test_conversion_retires_old_events_and_linked_unsent_deliveries(
    receipt_clients, test_database_engine,
):
    _, _, shipment_id = receipt_clients
    now = datetime.now(UTC)
    with Session(test_database_engine) as session, session.begin():
        old = OutboxMessage(
            event_type="shipment.receipt_confirmed", aggregate_type="shipment",
            aggregate_id=shipment_id, dedupe_key="old-receipt", payload={},
            status="completed", available_at=now,
        )
        session.add(old)
        session.flush()
        session.add(OutboxMessage(
            event_type="notification.delivery", aggregate_type="shipment",
            aggregate_id=shipment_id, dedupe_key="old-receipt-delivery", payload={},
            message_kind="delivery", source_event_id=old.id, status="processing",
            available_at=now, locked_by="old-worker", locked_at=now,
        ))
    preview = convert(test_database_engine)
    assert preview["retire"]
    convert(test_database_engine, expected_digest=preview["digest"])
    with Session(test_database_engine) as session:
        delivery = session.scalar(select(OutboxMessage).where(
            OutboxMessage.dedupe_key == "old-receipt-delivery",
        ))
        assert delivery.status == "completed"
        assert delivery.locked_by is None
        assert delivery.last_error_code == "receipt_notification_retired"


def test_conversion_backfills_withdrawn_first_time_without_receiving_draft_or_copies(
    receipt_clients, test_database_engine,
):
    _, factory, sid = receipt_clients
    url = f"/api/v1/factory/shipments/{sid}"
    detail = factory.get(url).json()
    assert factory.post(url + "/withdraw", json={
        "version": detail["version"], "reason": "历史撤回",
    }, headers={"Idempotency-Key": "historical-withdraw"}).status_code == 200
    with Session(test_database_engine) as session, session.begin():
        root = session.get(Shipment, sid)
        first = root.first_submitted_at
        root.first_submitted_at = None
    preview = convert(test_database_engine)
    assert preview["errors"] == []
    assert preview["convert"] == []
    assert sid in preview["excluded"]
    convert(test_database_engine, expected_digest=preview["digest"])
    with Session(test_database_engine) as session:
        assert session.get(Shipment, sid).first_submitted_at == first
        assert session.get(ShipmentReceipt, sid).status == "DRAFT"
        assert session.scalar(select(func.count()).select_from(ShipmentReceiptItem)) == 0


def test_precheck_reads_old_schema_but_apply_requires_migration(
    receipt_clients, test_database_engine, test_database_url,
):
    _, _, sid = receipt_clients
    make_historical(test_database_engine, sid)
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", test_database_url)
    command.downgrade(config, "20261009_0052")
    try:
        preview = convert(test_database_engine)
        assert preview["schemaReady"] is False
        assert preview["convert"] == [sid]
        with pytest.raises(ValueError, match="schema_required"):
            convert(test_database_engine, expected_digest=preview["digest"])
    finally:
        command.upgrade(config, "head")


def test_conversion_failure_does_not_leave_partial_receipts_or_first_times(
    receipt_clients, test_database_engine,
):
    _, _, sid = receipt_clients
    make_historical(test_database_engine, sid)
    preview = convert(test_database_engine)

    def fail_audit(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO audit_logs"):
            raise RuntimeError("conversion transaction failure")

    event.listen(test_database_engine, "before_cursor_execute", fail_audit)
    try:
        with pytest.raises(RuntimeError, match="transaction failure"):
            convert(test_database_engine, expected_digest=preview["digest"])
    finally:
        event.remove(test_database_engine, "before_cursor_execute", fail_audit)
    with Session(test_database_engine) as session:
        assert session.get(ShipmentReceipt, sid) is None
        assert session.get(Shipment, sid).first_submitted_at is None
