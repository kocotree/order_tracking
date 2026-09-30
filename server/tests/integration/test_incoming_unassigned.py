from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier

import pytest
from sqlalchemy import Engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.order_source import FakeFeishuOrderSource
from app.db.models import (
    Notification,
    Order,
    OrderAssignment,
    OrderDetail,
    ProductVariant,
    QuantityLedger,
)
from app.modules.incoming_differences import IncomingDifferenceService
from app.modules.incoming_differences.service import IncomingDifferenceValidationError
from app.modules.notifications_audit import NotificationsAuditService
from app.modules.orders.dispatch import OrderDispatchService
from app.modules.orders.service import OrderConflict, OrderService
from app.modules.orders.source_update import OrderSourceUpdateService
from tests.integration.test_incoming_differences import (
    ADMIN,
    BATCH_ID,
    FACTORY_A,
    FACTORY_B,
    FACTORY_USER,
    ORDER_ID,
    _line,
    _seed_batch,
    _seed_masters,
    _seed_order,
)
from tests.integration.test_order_source_update import setup_order


@pytest.mark.parametrize("lifecycle", ["DRAFT", "PUBLISHED", "COMPLETED"])
def test_unique_unassigned_zero_remaining_detail_matches_purchase(
    test_database_engine: Engine, lifecycle: str,
):
    with Session(test_database_engine) as session, session.begin():
        _seed_masters(session)
        assignment_id, _ = _seed_order(session)
        assignment = session.get(OrderAssignment, assignment_id)
        assignment.is_active = False
        detail = session.get(OrderDetail, "idf-detail-1")
        detail.assignment_id = None
        detail.dispatch_state = "UNASSIGNED"
        detail.source_shipped_quantity = 100
        session.get(Order, ORDER_ID).lifecycle = lifecycle
        session.get(ProductVariant, "idf-variant-1").properties_value = "红色110"
    service = IncomingDifferenceService(sessionmaker(test_database_engine))
    assert service.match_detail(
        factory_id=FACTORY_A, product_code="IDF-ITEM", product_name="来货测试产品",
        spec="红色110",
    ) == "idf-detail-1"


def test_unassigned_registration_and_adjustment_affect_order_quantity(test_database_engine: Engine):
    with Session(test_database_engine) as session, session.begin():
        _seed_masters(session)
        assignment_id, _ = _seed_order(session)
        session.get(OrderAssignment, assignment_id).is_active = False
        detail = session.get(OrderDetail, "idf-detail-1")
        detail.assignment_id = None
        detail.dispatch_state = "UNASSIGNED"
        detail.source_shipped_quantity = 10
        line = _line(assignment_id, -2)
        line.update(orderAssignmentId=None, detailId=detail.detail_id,
                    variantId=detail.matched_variant_id, factoryId=FACTORY_A)
        _seed_batch(session, lines=[line])
    sessions = sessionmaker(test_database_engine)
    service = IncomingDifferenceService(sessions)
    result = service.confirm(batch_id=BATCH_ID, workbook_version=1, actor_id=ADMIN)
    assert result.record_count == 1
    assert service.confirm(batch_id=BATCH_ID, workbook_version=1, actor_id=ADMIN).replayed
    record = service.list_for_order(actor_id=ADMIN, order_id=ORDER_ID)[0]
    assert record.quantity == -2
    orders = OrderService(sessions)
    assert orders.get(order_id=ORDER_ID).details[0].shipped_quantity == 8
    service.adjust_quantity(actor_id=ADMIN, order_id=ORDER_ID, record_id=record.record_id,
                            quantity=-3, version=record.version, request_id="adjust-pending")
    assert orders.get(order_id=ORDER_ID).details[0].shipped_quantity == 7
    listed, total = orders.list_visible(actor_id=ADMIN, include_drafts=True)
    assert total == 1
    assert listed[0].details[0].shipped_quantity == 7
    assert service.list_for_order(actor_id=FACTORY_USER, order_id=ORDER_ID) == []
    notifications = NotificationsAuditService(sessions)
    while notifications.consume_next_business_event(worker_id="pending-diff"):
        pass
    with sessions() as session:
        assert session.scalar(select(Notification.notification_id).where(
            Notification.category == "INCOMING_DIFF")) is None
    with pytest.raises(IncomingDifferenceValidationError, match="不能小于 0"):
        service.adjust_quantity(actor_id=ADMIN, order_id=ORDER_ID, record_id=record.record_id,
                                quantity=-11, version=2, request_id="negative")
    assert orders.get(order_id=ORDER_ID).details[0].shipped_quantity == 7
    dispatch = OrderDispatchService(sessions, source=FakeFeishuOrderSource([]))
    for attempt in range(2):
        order = orders.get(order_id=ORDER_ID)
        preview = dispatch.dispatch_preview(actor_id=ADMIN, order_id=ORDER_ID,
            version=order.version, detail_ids=["idf-detail-1"], request_id=f"preview-{attempt}")
        assert preview["all_ok"]
        dispatched = dispatch.dispatch_confirm(actor_id=ADMIN, order_id=ORDER_ID,
            version=order.version, preview_id=preview["preview_id"],
            idempotency_key=f"dispatch-{attempt}", request_id=f"dispatch-{attempt}")
        assert dispatched.details[0].shipped_quantity == 7
        assert service.list_for_order(actor_id=FACTORY_USER, order_id=ORDER_ID)[0].quantity == -3
        if attempt == 0:
            withdrawn = orders.withdraw_factory(actor_id=ADMIN, order_id=ORDER_ID,
                factory_id=FACTORY_A, version=dispatched.version,
                request_id="withdraw", idempotency_key="withdraw")
            assert withdrawn.details[0].shipped_quantity == 7


def test_unassigned_manual_quantity_preserves_difference_and_factory(
    test_database_engine: Engine,
):
    with Session(test_database_engine) as session, session.begin():
        _seed_masters(session)
        assignment_id, _ = _seed_order(session)
        session.get(OrderAssignment, assignment_id).is_active = False
        detail = session.get(OrderDetail, "idf-detail-1")
        detail.assignment_id = None
        detail.dispatch_state = "UNASSIGNED"
        detail.source_shipped_quantity = 10
        line = _line(assignment_id, 2)
        line.update(orderAssignmentId=None, detailId=detail.detail_id,
                    variantId=detail.matched_variant_id, factoryId=FACTORY_A)
        _seed_batch(session, lines=[line])
    sessions = sessionmaker(test_database_engine)
    incoming = IncomingDifferenceService(sessions)
    incoming.confirm(batch_id=BATCH_ID, workbook_version=1, actor_id=ADMIN)
    orders = OrderSourceUpdateService(sessions, source=FakeFeishuOrderSource([]))
    order = orders.get(order_id=ORDER_ID)
    with pytest.raises(OrderConflict, match="来货出入"):
        orders.save_fields(actor_id=ADMIN, order_id=ORDER_ID, version=order.version,
            detail_id="idf-detail-1", detail_version=order.details[0].version,
            changes={"factory_id": FACTORY_B}, request_id="change-factory")
    saved = orders.save_fields(actor_id=ADMIN, order_id=ORDER_ID, version=order.version,
        detail_id="idf-detail-1", detail_version=order.details[0].version,
        changes={"shipped_quantity": 0}, request_id="set-zero")
    assert saved.details[0].shipped_quantity == 0
    record = incoming.list_for_order(actor_id=ADMIN, order_id=ORDER_ID)[0]
    incoming.adjust_quantity(actor_id=ADMIN, order_id=ORDER_ID, record_id=record.record_id,
        quantity=3, version=record.version, request_id="adjust-after-manual")
    assert orders.get(order_id=ORDER_ID).details[0].shipped_quantity == 1
    with sessions() as session:
        assert session.scalar(select(QuantityLedger.quantity_delta).where(
            QuantityLedger.source_type == "ADMIN_ADJUSTMENT")) == -12


def test_source_refresh_preserves_pending_ledger_and_identity(test_database_engine: Engine):
    sessions, row, source, order_id = setup_order(test_database_engine, raw_fields={
        "_purchase": {"mainOrderId": "PO-1", "childOrderId": "POI-1"},
    })
    with sessions() as session, session.begin():
        _seed_masters(session)
        detail = session.scalar(select(OrderDetail).where(OrderDetail.order_id == order_id))
        line = _line(0, 5)
        line.update(orderAssignmentId=None, detailId=detail.detail_id,
                    variantId=detail.matched_variant_id, factoryId=detail.matched_factory_id)
        _seed_batch(session, lines=[line])
    incoming = IncomingDifferenceService(sessions)
    incoming.confirm(batch_id=BATCH_ID, workbook_version=1, actor_id=ADMIN)
    orders = OrderSourceUpdateService(sessions, source=source)
    source._pages = [[replace(row, shipped_quantity=10)]]
    orders.refresh_automatically(order_id=order_id, request_id="refresh-pending")
    assert orders.get(order_id=order_id).details[0].shipped_quantity == 15
    record = incoming.list_for_order(actor_id=ADMIN, order_id=order_id)[0]
    incoming.adjust_quantity(actor_id=ADMIN, order_id=order_id, record_id=record.record_id,
        quantity=-2, version=record.version, request_id="negative-diff")
    assert orders.get(order_id=order_id).details[0].shipped_quantity == 8
    for invalid in (
        replace(row, shipped_quantity=0),
        replace(row, shipped_quantity=10, factory_name="未知工厂"),
        replace(row, shipped_quantity=10, source_sku_id="unknown-sku"),
        replace(row, shipped_quantity=10, raw_fields={
            "_purchase": {"mainOrderId": "PO-OTHER", "childOrderId": "POI-OTHER"},
        }),
    ):
        source._pages = [[invalid]]
        with pytest.raises(OrderConflict, match="来货出入"):
            orders.refresh_automatically(order_id=order_id, request_id="invalid-refresh")
        assert orders.get(order_id=order_id).details[0].shipped_quantity == 8


def test_concurrent_pending_adjustments_cannot_make_shipped_negative(test_database_engine: Engine):
    with Session(test_database_engine) as session, session.begin():
        _seed_masters(session)
        assignment_id, _ = _seed_order(session)
        session.get(OrderAssignment, assignment_id).is_active = False
        detail = session.get(OrderDetail, "idf-detail-1")
        detail.assignment_id = None
        detail.dispatch_state = "UNASSIGNED"
        detail.source_shipped_quantity = 10
        lines = [_line(assignment_id, 1, row_number=row) for row in (2, 3)]
        for line in lines:
            line.update(orderAssignmentId=None, detailId=detail.detail_id,
                        variantId=detail.matched_variant_id, factoryId=FACTORY_A)
        _seed_batch(session, lines=lines)
    sessions = sessionmaker(test_database_engine)
    service = IncomingDifferenceService(sessions)
    service.confirm(batch_id=BATCH_ID, workbook_version=1, actor_id=ADMIN)
    records = service.list_for_order(actor_id=ADMIN, order_id=ORDER_ID)
    barrier = Barrier(2)

    def synchronize_reads(conn, cursor, statement, parameters, context, executemany):
        if "FROM users" in statement:
            barrier.wait(timeout=10)

    def adjust(record):
        try:
            service.adjust_quantity(actor_id=ADMIN, order_id=ORDER_ID,
                record_id=record.record_id, quantity=-6, version=record.version,
                request_id=f"concurrent-{record.record_id}")
            return "saved"
        except IncomingDifferenceValidationError:
            return "rejected"

    event.listen(test_database_engine, "after_cursor_execute", synchronize_reads)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(adjust, records))
    finally:
        event.remove(test_database_engine, "after_cursor_execute", synchronize_reads)
    assert sorted(results) == ["rejected", "saved"]
    assert OrderService(sessions).get(order_id=ORDER_ID).details[0].shipped_quantity == 5


@pytest.mark.parametrize("field,value", [
    ("factoryId", FACTORY_B), ("variantId", "idf-variant-2"),
    ("purchaseOrderId", "PO-OTHER"), ("purchaseOrderItemId", "POI-OTHER"),
    ("quantity", -12),
])
def test_pending_confirmation_rejects_changed_identity_and_negative_batch(
    test_database_engine: Engine, field: str, value: object,
):
    with Session(test_database_engine) as session, session.begin():
        _seed_masters(session)
        assignment_id, _ = _seed_order(session)
        session.get(OrderAssignment, assignment_id).is_active = False
        detail = session.get(OrderDetail, "idf-detail-1")
        detail.assignment_id = None
        detail.dispatch_state = "UNASSIGNED"
        detail.source_shipped_quantity = 10
        lines = [_line(assignment_id, 1, row_number=row) for row in (2, 3)]
        for line in lines:
            line.update(orderAssignmentId=None, detailId=detail.detail_id,
                        variantId=detail.matched_variant_id, factoryId=FACTORY_A)
        lines[1][field] = value
        _seed_batch(session, lines=lines)
    sessions = sessionmaker(test_database_engine)
    service = IncomingDifferenceService(sessions)
    with pytest.raises(IncomingDifferenceValidationError):
        service.confirm(batch_id=BATCH_ID, workbook_version=1, actor_id=ADMIN)
    assert service.list_for_order(actor_id=ADMIN, order_id=ORDER_ID) == []
    assert OrderService(sessions).get(order_id=ORDER_ID).details[0].shipped_quantity == 10
