"""Regression coverage for Issue #260 through the scheduled synchronization entry point."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, select

from app.adapters.order_source import FakeFeishuOrderSource
from app.db.models import (
    AuditLog,
    IncomingDiffRecord,
    Order,
    OrderAssignment,
    OrderDetail,
    OrderImportRun,
    OrderImportSourceRecord,
    OutboxMessage,
    ProductVariant,
    QuantityLedger,
    ShipmentWritebackFact,
)
from app.modules.incoming_differences import IncomingDifferenceService
from app.modules.order_import.auto_sync import OrderAutoSync
from app.modules.orders.dispatch import OrderDispatchService
from app.modules.shipment_writeback.facts import shipment_lines
from app.modules.shipments.service import DraftBoxInput, DraftItemInput, ShipmentService
from tests.integration.test_incoming_differences import BATCH_ID, _line, _seed_batch, _seed_masters
from tests.integration.test_order_auto_sync import complete_cycle
from tests.integration.test_order_dispatch import _row, _seed_factory_b, setup_dispatch_order

NOW = datetime(2026, 11, 20, 8, tzinfo=UTC)


def purchase_row(record_id="original", *, factory="测试工厂", quantity=100, shipped=0, po="PO-A"):
    return _row(
        record_id,
        factory_name=factory,
        order_quantity=quantity,
        shipped_quantity=shipped,
        pending_quantity=quantity - shipped,
        source_detail_id="detail-" + record_id,
        raw_fields={
            "下单数": quantity,
            "_purchase": {
                "mainOrderId": po,
                "childOrderId": po + "-item",
                "skuId": "6970000000001",
                "qty": quantity,
                "inQty": shipped,
            },
        },
    )


def cycle(sessions, source, now=NOW):
    sync = OrderAutoSync(sessions, source=source, clock=lambda: now)
    run_id = sync.ensure_due()
    assert run_id
    complete_cycle(sync, run_id)
    return run_id


def submit(sessions, assignment_id, quantity=30):
    shipments = ShipmentService(sessions)
    draft, _ = shipments.create_or_reuse_draft(
        actor_id="factory-import-user",
        factory_id="factory-import",
        preferred_order_id=None,
    )
    shipments.save_draft(
        actor_id="factory-import-user",
        factory_id="factory-import",
        shipment_id=draft.shipment_id,
        boxes=[
            DraftBoxInput(
                box_no=1,
                group_key=None,
                items=[
                    DraftItemInput(
                        assignment_id=assignment_id,
                        quantity=quantity,
                    )
                ],
            )
        ],
        note="",
    )
    return shipments.submit_draft(
        actor_id="factory-import-user",
        factory_id="factory-import",
        shipment_id=draft.shipment_id,
        idempotency_key=draft.shipment_id,
        now=NOW - timedelta(days=2),
    )


def test_fully_assigned_order_receives_new_size_even_when_source_is_fully_shipped(
    test_database_engine: Engine,
):
    sessions, source, order_id = setup_dispatch_order(test_database_engine, rows=[purchase_row()])
    service = OrderDispatchService(sessions, source=source)
    service.dispatch_automatically(order_id=order_id, request_id="initial")
    with sessions() as session, session.begin():
        session.add(
            ProductVariant(
                variant_id="variant-new-size",
                product_id="product-import",
                source_sku_id="6970000000002",
                properties_value="红色 / 120",
                source_category="童帽春夏",
                source_enabled=1,
                is_available=True,
                source_modified_at=NOW.replace(tzinfo=None),
                first_synced_at=NOW.replace(tzinfo=None),
                last_synced_at=NOW.replace(tzinfo=None),
            )
        )
    new = replace(
        purchase_row("new", quantity=40, shipped=40, po="PO-NEW"),
        source_sku_id="6970000000002",
        properties_value="红色 / 120",
    )
    source._pages = [[purchase_row(), new]]
    cycle(sessions, source)
    order = service.get(order_id=order_id)
    assert len(order.details) == 2
    assert order.total_quantity == 140
    assert all(d.dispatch_state == "ASSIGNED" for d in order.details)
    assert (
        next(d for d in order.details if d.source_sku_id == new.source_sku_id).shipped_quantity
        == 40
    )
    cycle(sessions, source, NOW + timedelta(minutes=20))
    with sessions() as session:
        assert len(list(session.scalars(select(OrderAssignment)))) == 2
        assert (
            len(
                list(
                    session.scalars(
                        select(OutboxMessage).where(
                            OutboxMessage.event_type == "order_detail_dispatched"
                        )
                    )
                )
            )
            == 2
        )


@pytest.mark.parametrize("keeper_quantity", [60, 20])
def test_factory_split_rebinds_by_purchase_identity_and_preserves_execution_history(
    test_database_engine: Engine,
    keeper_quantity: int,
):
    sessions, source, order_id = setup_dispatch_order(test_database_engine, rows=[purchase_row()])
    _seed_factory_b(test_database_engine)
    service = OrderDispatchService(sessions, source=source)
    service.dispatch_automatically(order_id=order_id, request_id="initial")
    with sessions() as session:
        old = session.scalar(select(OrderDetail))
        old_detail_id, assignment_id = old.detail_id, old.assignment_id
    shipment = submit(sessions, assignment_id)
    with sessions() as session:
        ledger_before = [
            (r.ledger_id, r.quantity_delta, r.order_assignment_id)
            for r in session.scalars(select(QuantityLedger))
        ]
        captured_before = [r.lines for r in session.scalars(select(ShipmentWritebackFact))]
        assert captured_before and captured_before[0][0]["record_id"] == "original"
    keeper = purchase_row("keeper", quantity=keeper_quantity, shipped=30)
    moved = purchase_row(
        "original", factory="测试工厂B", quantity=100 - keeper_quantity, shipped=5, po="PO-B"
    )
    source._pages = [[moved, keeper]]
    run_id = cycle(sessions, source)
    order = service.get(order_id=order_id)
    with sessions() as session:
        assert ledger_before == [
            (r.ledger_id, r.quantity_delta, r.order_assignment_id)
            for r in session.scalars(select(QuantityLedger))
        ]
        assert captured_before == [r.lines for r in session.scalars(select(ShipmentWritebackFact))]
        old = session.get(OrderDetail, old_detail_id)
        assert old.assignment_id == assignment_id
        assert session.get(OrderAssignment, assignment_id).initial_shipped_quantity == 0
        if keeper_quantity < 30:
            assert len(order.details) == 1
            assert old.order_quantity == 100
            assert session.get(OrderImportRun, run_id).sync_result["failed_orders"] == 1
            return
        assert len(order.details) == 2
        assert order.total_quantity == 100 and order.shipped_quantity == 35
        assert old.order_quantity == keeper_quantity and old.factory_name == "测试工厂"
        assert (
            session.get(OrderImportSourceRecord, old.source_record_pk).source_record_id == "keeper"
        )
        assert shipment_lines(session, shipment.shipment_id)[0]["record_id"] == "keeper"
    assert {(d.factory_name, d.order_quantity, d.shipped_quantity) for d in order.details} == {
        ("测试工厂", 60, 30),
        ("测试工厂B", 40, 5),
    }
    factory_view = service.get_visible(actor_id="factory-b-user", order_id=order_id)
    assert factory_view.total_quantity == 40 and factory_view.shipped_quantity == 5
    cycle(sessions, source, NOW + timedelta(minutes=20))
    assert service.get(order_id=order_id).shipped_quantity == 35
    later = submit(sessions, assignment_id, quantity=10)
    with sessions() as session:
        fact = session.scalar(
            select(ShipmentWritebackFact).where(
                ShipmentWritebackFact.root_id == later.shipment_id,
            )
        )
        assert fact.lines[0]["record_id"] == "keeper"
        assert fact.lines[0]["assignment_id"] == assignment_id
    assert service.get(order_id=order_id).shipped_quantity == 45


@pytest.mark.parametrize("conflict", ["purchase", "total", "manual", "duplicate", "removed"])
def test_unsafe_changes_roll_back_the_entire_order(test_database_engine: Engine, conflict):
    sessions, source, order_id = setup_dispatch_order(test_database_engine, rows=[purchase_row()])
    _seed_factory_b(test_database_engine)
    service = OrderDispatchService(sessions, source=source)
    service.dispatch_automatically(order_id=order_id, request_id="initial")
    original = purchase_row()
    keeper = purchase_row("keeper", quantity=60)
    moved = purchase_row("original", factory="测试工厂B", quantity=40, po="PO-B")
    rows = [moved, keeper]
    if conflict == "purchase":
        rows = [purchase_row(po="OTHER"), purchase_row("new", quantity=10, po="NEW")]
    elif conflict == "total":
        rows = [moved, purchase_row("keeper", quantity=61)]
    elif conflict == "manual":
        with sessions() as session, session.begin():
            session.scalar(select(OrderDetail)).shipped_override_enabled = True
    elif conflict == "duplicate":
        rows = [original, purchase_row("duplicate")]
    elif conflict == "removed":
        rows = [purchase_row("unrelated", factory="测试工厂B", po="OTHER")]
    source._pages = [rows]
    before = service.get(order_id=order_id)
    run_id = cycle(sessions, source)
    assert service.get(order_id=order_id) == before
    with sessions() as session:
        assert session.get(OrderImportRun, run_id).sync_result["failed_orders"] == 1
        assert len(list(session.scalars(select(OrderImportSourceRecord)))) == 1


def test_unchanged_assigned_orders_do_not_repeat_purchase_reads(test_database_engine: Engine):
    sessions, source, order_id = setup_dispatch_order(test_database_engine, rows=[purchase_row()])
    service = OrderDispatchService(sessions, source=source)
    service.dispatch_automatically(order_id=order_id, request_id="initial")
    cycle(sessions, source)
    calls = []
    read = source.read_records

    def tracked(record_ids, *, purchase_links=None):
        calls.append(record_ids)
        return read(record_ids, purchase_links=purchase_links)

    source.read_records = tracked
    before = service.get(order_id=order_id)
    cycle(sessions, source, NOW + timedelta(minutes=20))
    assert calls == []
    assert service.get(order_id=order_id) == before


@pytest.mark.parametrize("protected", ["completed", "deleted", "manual"])
def test_protected_orders_do_not_receive_new_rows(test_database_engine: Engine, protected):
    sessions, source, order_id = setup_dispatch_order(test_database_engine, rows=[purchase_row()])
    with sessions() as session, session.begin():
        order = session.get(Order, order_id)
        if protected == "completed":
            order.lifecycle = "COMPLETED"
        elif protected == "deleted":
            order.deleted_at = NOW.replace(tzinfo=None)
        else:
            order.source = "manual"
    source._pages = [[purchase_row(), purchase_row("new", po="NEW")]]
    cycle(sessions, source)
    with sessions() as session:
        assert len(list(session.scalars(select(OrderDetail)))) == 1


def test_new_incomplete_row_stays_draft_and_withdrawal_pause_survives(test_database_engine: Engine):
    sessions, source, order_id = setup_dispatch_order(test_database_engine, rows=[purchase_row()])
    with sessions() as session, session.begin():
        detail = session.scalar(select(OrderDetail))
        detail.auto_dispatch_paused = True
        detail.shipped_override_enabled = True
        detail.source_shipped_quantity = 0
        detail.date_override_enabled = True
        detail.contract_ship_date = None
    source._pages = [
        [
            purchase_row(shipped=20),
            replace(
                purchase_row("incomplete", po="NEW"),
                source_sku_id=None,
                factory_name=None,
            ),
        ]
    ]
    cycle(sessions, source)
    with sessions() as session:
        details = list(session.scalars(select(OrderDetail).order_by(OrderDetail.sort_order)))
        assert len(details) == 2
        assert all(d.dispatch_state == "UNASSIGNED" for d in details)
        assert details[0].auto_dispatch_paused and details[0].source_shipped_quantity == 0
        assert details[0].contract_ship_date is None
        assert details[1].parse_issues


def test_dispatch_failure_after_reconciliation_recovers_without_duplicate_rows(
    test_database_engine: Engine,
    monkeypatch,
):
    sessions, source, order_id = setup_dispatch_order(test_database_engine, rows=[purchase_row()])
    _seed_factory_b(test_database_engine)
    service = OrderDispatchService(sessions, source=source)
    service.dispatch_automatically(order_id=order_id, request_id="initial")
    source._pages = [
        [
            purchase_row(),
            purchase_row(
                "new",
                factory="测试工厂B",
                quantity=40,
                po="NEW",
            ),
        ]
    ]
    sync = OrderAutoSync(sessions, source=source, clock=lambda: NOW)

    def failed_dispatch(**kwargs):
        raise RuntimeError("simulated dispatch interruption")

    monkeypatch.setattr(sync._orders, "dispatch_automatically", failed_dispatch)
    run_id = sync.ensure_due()
    complete_cycle(sync, run_id)
    assert len(service.get(order_id=order_id).details) == 2
    cycle(sessions, source, NOW + timedelta(minutes=20))
    order = service.get(order_id=order_id)
    assert len(order.details) == 2 and order.total_quantity == 140
    assert all(d.dispatch_state == "ASSIGNED" for d in order.details)
    with sessions() as session:
        assert len(list(session.scalars(select(OrderAssignment)))) == 2
        assert session.scalar(
            select(AuditLog).where(
                AuditLog.action == "order_sync.step",
                AuditLog.target_id == order_id,
            )
        )


@pytest.mark.parametrize("keeper_quantity", [31, 60])
def test_incoming_difference_stays_on_original_assignment_and_limits_split(
    test_database_engine: Engine,
    keeper_quantity,
):
    sessions, source, order_id = setup_dispatch_order(test_database_engine, rows=[purchase_row()])
    _seed_factory_b(test_database_engine)
    service = OrderDispatchService(sessions, source=source)
    service.dispatch_automatically(order_id=order_id, request_id="initial")
    with sessions() as session:
        assignment_id = session.scalar(select(OrderDetail.assignment_id))
    submit(sessions, assignment_id)
    with sessions() as session, session.begin():
        _seed_masters(session)
        _seed_batch(
            session,
            submitter_id="admin-order-import",
            lines=[
                _line(
                    assignment_id,
                    2,
                    purchase_order_id="PO-A",
                    purchase_order_item_id="PO-A-item",
                )
            ],
        )
    incoming = IncomingDifferenceService(sessions)
    incoming.confirm(batch_id=BATCH_ID, workbook_version=1, actor_id="admin-order-import")
    with sessions() as session:
        record = session.scalar(select(IncomingDiffRecord))
        identity_before = (
            record.detail_id,
            record.order_assignment_id,
            record.purchase_order_id,
            record.purchase_order_item_id,
            record.quantity,
        )
    source._pages = [
        [
            purchase_row("original", factory="测试工厂B", quantity=100 - keeper_quantity, po="NEW"),
            purchase_row("keeper", quantity=keeper_quantity, shipped=32),
        ]
    ]
    run_id = cycle(sessions, source)
    with sessions() as session:
        record = session.scalar(select(IncomingDiffRecord))
        assert identity_before == (
            record.detail_id,
            record.order_assignment_id,
            record.purchase_order_id,
            record.purchase_order_item_id,
            record.quantity,
        )
        assert session.get(OrderImportRun, run_id).sync_result["failed_orders"] == (
            1 if keeper_quantity < 32 else 0
        )
    assert service.get(order_id=order_id).shipped_quantity == 32


def test_complete_source_removal_is_a_conflict_without_deleting_system_details(
    test_database_engine: Engine,
):
    sessions, source, order_id = setup_dispatch_order(test_database_engine, rows=[purchase_row()])
    service = OrderDispatchService(sessions, source=source)
    service.dispatch_automatically(order_id=order_id, request_id="initial")
    source._pages = [[]]
    before = service.get(order_id=order_id)
    run_id = cycle(sessions, source)
    assert service.get(order_id=order_id) == before
    with sessions() as session:
        assert session.get(OrderImportRun, run_id).sync_result["failed_orders"] == 1


def test_raw_factory_split_is_not_hidden_by_stale_erp_quantity(test_database_engine: Engine):
    sessions, source, order_id = setup_dispatch_order(test_database_engine, rows=[purchase_row()])
    _seed_factory_b(test_database_engine)
    service = OrderDispatchService(sessions, source=source)
    service.dispatch_automatically(order_id=order_id, request_id="initial")
    source._pages = [
        [
            replace(purchase_row(quantity=60), order_quantity=100),
            purchase_row("new", factory="测试工厂B", quantity=40, po="NEW"),
        ]
    ]
    before = service.get(order_id=order_id)
    run_id = cycle(sessions, source)
    assert service.get(order_id=order_id) == before
    with sessions() as session:
        assert session.get(OrderImportRun, run_id).sync_result["failed_orders"] == 1


def test_split_new_factory_requires_exact_purchase_baseline(test_database_engine: Engine):
    sessions, source, order_id = setup_dispatch_order(test_database_engine, rows=[purchase_row()])
    _seed_factory_b(test_database_engine)
    service = OrderDispatchService(sessions, source=source)
    service.dispatch_automatically(order_id=order_id, request_id="initial")
    source._pages = [
        [
            purchase_row(quantity=60),
            replace(
                purchase_row("new", factory="测试工厂B", quantity=40),
                raw_fields={"下单数": 40},
            ),
        ]
    ]
    before = service.get(order_id=order_id)
    run_id = cycle(sessions, source)
    assert service.get(order_id=order_id) == before
    with sessions() as session:
        assert session.get(OrderImportRun, run_id).sync_result["failed_orders"] == 1


def test_source_detail_identity_change_triggers_reconciliation(test_database_engine: Engine):
    sessions, source, order_id = setup_dispatch_order(test_database_engine, rows=[purchase_row()])
    service = OrderDispatchService(sessions, source=source)
    service.dispatch_automatically(order_id=order_id, request_id="initial")
    cycle(sessions, source)
    source._pages = [[replace(purchase_row(), source_detail_id="different-detail")]]
    before = service.get(order_id=order_id)
    run_id = cycle(sessions, source, NOW + timedelta(minutes=20))
    assert service.get(order_id=order_id) == before
    with sessions() as session:
        assert session.get(OrderImportRun, run_id).sync_result["failed_orders"] == 1


def test_concurrent_order_edit_during_source_read_is_not_overwritten(test_database_engine: Engine):
    sessions, source, order_id = setup_dispatch_order(test_database_engine, rows=[purchase_row()])
    service = OrderDispatchService(sessions, source=source)
    service.dispatch_automatically(order_id=order_id, request_id="initial")

    class ConcurrentSource(FakeFeishuOrderSource):
        def read_records(self, record_ids, *, purchase_links=None):
            with sessions() as session, session.begin():
                session.get(Order, order_id).version += 1
            return super().read_records(record_ids, purchase_links=purchase_links)

    changed_source = ConcurrentSource([[purchase_row(), purchase_row("new", po="NEW")]])
    run_id = cycle(sessions, changed_source)
    assert len(service.get(order_id=order_id).details) == 1
    with sessions() as session:
        assert session.get(OrderImportRun, run_id).sync_result["failed_orders"] == 1


def test_split_existing_unassigned_target_also_requires_exact_purchase(
    test_database_engine: Engine,
):
    target = replace(
        purchase_row("target", factory="测试工厂B", quantity=20),
        raw_fields={"下单数": 20},
        contract_ship_date=None,
    )
    sessions, source, order_id = setup_dispatch_order(
        test_database_engine,
        rows=[purchase_row(), target],
    )
    _seed_factory_b(test_database_engine)
    service = OrderDispatchService(sessions, source=source)
    service.dispatch_automatically(order_id=order_id, request_id="initial")
    assert sum(d.dispatch_state == "ASSIGNED" for d in service.get(order_id=order_id).details) == 1
    source._pages = [
        [
            purchase_row(quantity=60),
            replace(
                purchase_row("target", factory="测试工厂B", quantity=60),
                raw_fields={"下单数": 60},
            ),
        ]
    ]
    before = service.get(order_id=order_id)
    run_id = cycle(sessions, source)
    assert service.get(order_id=order_id) == before
    with sessions() as session:
        assert session.get(OrderImportRun, run_id).sync_result["failed_orders"] == 1
