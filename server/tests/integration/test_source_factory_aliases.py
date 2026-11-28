"""Confirmed factory names share an identity without migrating execution history."""

from datetime import timedelta

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.order_source import FakeFeishuOrderSource
from app.db.models import (
    Factory,
    IncomingDiffRecord,
    OrderAssignment,
    OrderDetail,
    OrderImportRun,
    OrderLine,
    OutboxMessage,
    QuantityLedger,
    Shipment,
    ShipmentBox,
    ShipmentBoxItem,
    ShipmentLine,
    ShipmentReceipt,
    ShipmentReceiptItem,
    ShipmentWritebackFact,
    User,
)
from app.modules.incoming_differences import IncomingDifferenceService
from app.modules.order_import import OrderImportService
from app.modules.orders.dispatch import OrderDispatchService
from tests.integration.test_incoming_differences import BATCH_ID, _line, _seed_batch, _seed_masters
from tests.integration.test_order_dispatch import setup_dispatch_order
from tests.integration.test_order_import import _seed_import_dependencies
from tests.integration.test_order_reconciliation import NOW, cycle, purchase_row, submit

ALIASES = [
    ("千与", "邯郸千与"),
    ("邯郸千与", "千与"),
    ("昱斌", "昱斌服饰"),
    ("昱斌服饰", "昱斌"),
]


@pytest.mark.parametrize(("stored", "incoming"), ALIASES)
def test_new_order_alias_imports_and_dispatches_to_existing_factory(
    test_database_engine: Engine, stored: str, incoming: str,
):
    _seed_import_dependencies(test_database_engine)
    sessions = sessionmaker(test_database_engine, expire_on_commit=False)
    with sessions() as session, session.begin():
        session.get(Factory, "factory-import").factory_name = stored
    source = FakeFeishuOrderSource([[purchase_row(factory=incoming)]])
    run_id = cycle(sessions, source)
    with sessions() as session:
        detail = session.scalar(select(OrderDetail))
        assert detail.matched_factory_id == "factory-import"
        assert detail.factory_name == incoming  # original source name remains traceable
        assert detail.dispatch_state == "ASSIGNED"
        assignment = session.get(OrderAssignment, detail.assignment_id)
        assert assignment.factory_id == "factory-import"
        assert session.get(OrderImportRun, run_id).sync_result["failed_orders"] == 0
        assert session.scalar(select(Factory).where(Factory.factory_name == incoming)) is None


@pytest.mark.parametrize(("stored", "incoming"), ALIASES)
def test_pending_source_alias_keeps_matching_identity(
    test_database_engine: Engine, stored: str, incoming: str,
):
    sessions, source, oid = setup_dispatch_order(test_database_engine, rows=[purchase_row()])
    with sessions() as session, session.begin():
        session.get(Factory, "factory-import").factory_name = stored
    source._pages = [[purchase_row(factory=incoming)]]
    service = OrderDispatchService(sessions, source=source)
    service.refresh_automatically(order_id=oid, request_id="alias-refresh")
    detail = service.get(order_id=oid).details[0]
    assert detail.dispatch_state == "UNASSIGNED"
    assert detail.matched_factory_id == "factory-import"
    with sessions() as session:
        assert "FACTORY_NOT_MATCHED" not in session.get(OrderDetail, detail.detail_id).parse_issues


def _execution_facts(session: Session):
    models = (
        OrderAssignment, OrderLine, QuantityLedger, IncomingDiffRecord,
        Shipment, ShipmentBox, ShipmentBoxItem, ShipmentLine,
        ShipmentReceipt, ShipmentReceiptItem, ShipmentWritebackFact, OutboxMessage,
    )
    return {
        model.__tablename__: list(session.execute(
            select(model.__table__).order_by(*model.__table__.primary_key.columns)
        ).mappings())
        for model in models
    }


@pytest.mark.parametrize(("stored", "incoming"), ALIASES)
def test_scheduled_alias_change_preserves_shipped_assignment_and_frozen_facts(
    test_database_engine: Engine, stored: str, incoming: str,
):
    sessions, source, oid = setup_dispatch_order(test_database_engine, rows=[purchase_row()])
    with sessions() as session, session.begin():
        session.get(Factory, "factory-import").factory_name = stored
    source._pages = [[purchase_row(factory=stored)]]
    service = OrderDispatchService(sessions, source=source, clock=lambda: NOW)
    service.refresh_automatically(order_id=oid, request_id="initial-refresh")
    service.dispatch_automatically(order_id=oid, request_id="initial-dispatch")
    with sessions() as session:
        assignment_id = session.scalar(select(OrderDetail.assignment_id))
    submit(sessions, assignment_id, quantity=30)
    with sessions() as session, session.begin():
        _seed_masters(session)
        _seed_batch(session, submitter_id="admin-order-import", lines=[
            _line(assignment_id, 2, purchase_order_id="PO-A", purchase_order_item_id="PO-A-item")
        ])
    IncomingDifferenceService(sessions).confirm(
        batch_id=BATCH_ID, workbook_version=1, actor_id="admin-order-import",
    )
    before = service.get(order_id=oid)
    assert before.shipped_quantity == 32
    with sessions() as session:
        history = _execution_facts(session)
        assert history["shipment_writeback_facts"]
        assert history["incoming_diff_records"]
    # Changed ERP receipt totals cannot replace the fixed execution baseline.
    source._pages = [[purchase_row(factory=incoming, shipped=90)]]
    for offset in (0, 20):
        run_id = cycle(sessions, source, NOW + timedelta(minutes=offset))
        assert service.get(order_id=oid) == before
        with sessions() as session:
            assert session.get(OrderImportRun, run_id).sync_result["failed_orders"] == 0
            assert _execution_facts(session) == history
            assert session.scalar(select(OrderDetail.assignment_id)) == assignment_id
    factory_view = service.get_visible(actor_id="factory-import-user", order_id=oid)
    assert factory_view.total_quantity == 100 and factory_view.shipped_quantity == 32


@pytest.mark.parametrize("incoming", ["千与", "邯郸千与"])
def test_two_enabled_alias_records_are_ambiguous(test_database_engine: Engine, incoming: str):
    _seed_import_dependencies(test_database_engine)
    with Session(test_database_engine) as session, session.begin():
        session.get(Factory, "factory-import").factory_name = "千与"
        session.add(Factory(factory_id="duplicate", factory_name="邯郸千与",
                            supplier_number="DUP", factory_code="DUP", is_enabled=True))
    with Session(test_database_engine) as session:
        _, factory, issues = OrderImportService.match_source_row(
            session, purchase_row(factory=incoming),
        )
        assert factory is None
        assert "FACTORY_NOT_MATCHED" in issues


@pytest.mark.parametrize("condition", ["disabled", "no_account", "unknown"])
def test_alias_does_not_bypass_existing_factory_validation(
    test_database_engine: Engine, condition: str,
):
    _seed_import_dependencies(test_database_engine)
    with Session(test_database_engine) as session, session.begin():
        factory = session.get(Factory, "factory-import")
        factory.factory_name = "千与"
        if condition == "disabled":
            factory.is_enabled = False
        if condition == "no_account":
            session.get(User, "factory-import-user").is_enabled = False
    with Session(test_database_engine) as session:
        _, factory, issues = OrderImportService.match_source_row(
            session, purchase_row(factory="千与服饰" if condition == "unknown" else "邯郸千与"),
        )
        if condition == "no_account":
            assert factory is not None and factory.factory_id == "factory-import"
            assert "FACTORY_HAS_NO_ENABLED_USER" in issues
        else:
            assert factory is None and "FACTORY_NOT_MATCHED" in issues
