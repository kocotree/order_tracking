from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from time import perf_counter
from typing import Any

import pytest
from sqlalchemy import Engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import (
    AuditLog,
    Factory,
    Order,
    OrderAssignment,
    OrderDetail,
    QuantityLedger,
    User,
)
from app.modules.contracts import ContractService
from app.modules.orders import OrderService
from tests.api.test_shipment_api import ADMIN_ID, FACTORY_IDS, ORDER_ID, USER_IDS, _seed


@contextmanager
def measured_queries(engine: Engine) -> Iterator[list[str]]:
    statements: list[str] = []

    def record(_conn: Any, _cursor: Any, statement: str, *_args: Any) -> None:
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    started = perf_counter()
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", record)
        print(f"queries={len(statements)} elapsed_ms={(perf_counter() - started) * 1000:.2f}")


@pytest.mark.parametrize("actor", [None, ADMIN_ID, USER_IDS[0]])
def test_order_detail_batches_quantities_and_preserves_factory_scope(
    test_database_engine: Engine, actor: str | None,
) -> None:
    assignment_id = _seed(test_database_engine, initial_shipped_quantity=10)
    reader = OrderService(sessionmaker(test_database_engine, expire_on_commit=False))

    def read():  # type: ignore[no-untyped-def]
        return reader.get(order_id=ORDER_ID) if actor is None else reader.get_visible(
            actor_id=actor, order_id=ORDER_ID,
        )

    with measured_queries(test_database_engine) as small:
        assert read().shipped_quantity == 10
    with Session(test_database_engine) as session, session.begin():
        original = session.get(OrderAssignment, assignment_id)
        assert original
        for index in range(30):
            assignment = OrderAssignment(
                order_line_id=original.order_line_id,
                factory_id=FACTORY_IDS[index % 2], factory_name_snapshot=f"工厂{index % 2}",
                assigned_quantity=10, initial_shipped_quantity=2,
                contract_ship_date=date(2026, 9, 1), is_active=index != 29,
            )
            session.add(assignment)
            session.flush()
            session.add(QuantityLedger(
                order_assignment_id=assignment.order_assignment_id,
                source_type="shipment", source_id=f"quantity-{index}",
                quantity_delta=3, actor_id=ADMIN_ID, created_at=datetime(2026, 10, 9),
            ))
    with measured_queries(test_database_engine) as large:
        result = read()
    assert result.shipped_quantity == (85 if actor == USER_IDS[0] else 155)
    if actor == USER_IDS[0]:
        assert {a.factory_id for line in result.lines for a in line.assignments} == {FACTORY_IDS[0]}
    assert len(large) == len(small)


def test_audit_operator_queries_do_not_grow_with_log_count(test_database_engine: Engine) -> None:
    _seed(test_database_engine)
    with Session(test_database_engine) as session, session.begin():
        for index in range(20):
            actor = f"audit-reader-{index}"
            session.add(User(user_id=actor, role="admin", is_enabled=True,
                             feishu_display_name=f"操作人{index}"))
            session.add(AuditLog(request_id=f"audit-{index}", action="test", target_type="order",
                                 target_id=ORDER_ID, changes={}, actor_id=actor))
        session.add(AuditLog(request_id="system", action="test", target_type="order",
                             target_id=ORDER_ID, changes={}, actor_id=None))
        session.add(AuditLog(request_id="missing", action="test", target_type="order",
                             target_id=ORDER_ID, changes={}, actor_id="missing-user"))
    reader = OrderService(sessionmaker(test_database_engine, expire_on_commit=False))
    with measured_queries(test_database_engine) as queries:
        result = reader.list_audit_logs(actor_id=ADMIN_ID, order_id=ORDER_ID)
    assert [row.operator_name for row in result] == ["系统", "系统"] + [
        f"操作人{index}" for index in reversed(range(20))
    ]
    assert len(queries) <= 5


def test_contract_status_batches_factories_and_detail_validation(
    test_database_engine: Engine,
) -> None:
    _seed(test_database_engine)
    with Session(test_database_engine) as session, session.begin():
        order = session.get(Order, ORDER_ID)
        assert order
        order.detail_mode = True
        for index in range(20):
            factory_id = f"contract-query-{index:02}"
            session.add(Factory(
                factory_id=factory_id, factory_name=f"合同工厂{index}",
                supplier_number=f"CQ{index}",
                factory_code=f"CQ{chr(65 + index)}", legal_name="测试工厂", address="测试地址",
                legal_representative="测试法人" if index != 1 else None,
            ))
            session.flush()
            session.add(OrderDetail(
                detail_id=f"contract-query-{index}", order_id=ORDER_ID, origin="manual",
                sort_order=index, accepted_raw_fields={}, matched_factory_id=factory_id,
                matched_variant_id="shipment-api-variant" if index != 2 else None,
                order_quantity=10 if index != 3 else None,
                parse_issues=[], dispatch_state="UNASSIGNED",
                created_at=datetime(2026, 10, 9), updated_at=datetime(2026, 10, 9),
            ))
    reader = ContractService(sessionmaker(test_database_engine, expire_on_commit=False))
    with measured_queries(test_database_engine) as queries:
        result = reader.list_for_order(actor_id=ADMIN_ID, order_id=ORDER_ID)
    assert len(result) == 20
    assert [row.ineligible_reason for row in result[:4]] == [
        None, "factory_contract_incomplete",
        "contract_details_incomplete", "contract_details_incomplete",
    ]
    assert all(row.eligible for row in result[4:])
    assert len(queries) <= 7
