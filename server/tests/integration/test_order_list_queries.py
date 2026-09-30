from datetime import date, datetime
from statistics import median
from time import perf_counter

import pytest
from sqlalchemy import Engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Order, OrderAssignment, OrderDetail, OrderLine, QuantityLedger
from app.modules.orders import OrderService
from tests.integration.test_order_lifecycle import _seed_order_dependencies
from tests.integration.test_order_pagination import ordered_snapshots


def seed_source_orders(engine: Engine, count: int = 40) -> str:
    admin, factory, _, variant = _seed_order_dependencies(engine)
    now = datetime(2026, 9, 30)
    with Session(engine) as session, session.begin():
        for index in range(count):
            order_id = f"query-{index:04d}"
            session.add(Order(
                order_id=order_id, order_no=order_id, source="manual", tracker="松子",
                lifecycle=["DRAFT", "PUBLISHED", "COMPLETED"][index % 3],
                detail_mode=True, created_by=admin, updated_by=admin,
            ))
            session.flush()
            line = OrderLine(
                order_id=order_id, product_variant_id=variant, order_quantity=30,
                sku_id_snapshot="SKU", product_name_snapshot="测试产品",
                properties_value_snapshot="蓝色",
            )
            session.add(line)
            session.flush()
            assignment = OrderAssignment(
                order_line_id=line.order_line_id, factory_id=factory,
                assigned_quantity=30, initial_shipped_quantity=4,
                factory_name_snapshot="工厂甲", is_active=index % 2 == 0,
                contract_ship_date=date(2026, 9, 12),
            )
            session.add(assignment)
            session.flush()
            for number in range(3):
                detail = OrderDetail(
                    detail_id=f"{order_id}-{number}", order_id=order_id, origin="manual",
                    sort_order=number, accepted_raw_fields={}, parse_issues=[],
                    product_name="测试产品", source_sku_id="SKU", properties_value="蓝色",
                    matched_variant_id=variant, matched_factory_id=factory,
                    factory_name="工厂甲", order_quantity=30,
                    source_shipped_quantity=None if index % 7 == 0 else 10,
                    contract_ship_date=None if index % 5 == 0 else date(2026, 9, index % 28 + 1),
                    assignment_id=assignment.order_assignment_id if number == 2 else None,
                    dispatch_state="ASSIGNED" if number == 2 else "UNASSIGNED",
                    created_at=now, updated_at=now,
                )
                session.add(detail)
                session.flush()
                session.add(QuantityLedger(
                    order_detail_id=detail.detail_id,
                    source_type="incoming_difference", source_id=detail.detail_id,
                    quantity_delta=-2 if number == 0 else 5, actor_id=admin, created_at=now,
                ))
            session.add(QuantityLedger(
                order_assignment_id=assignment.order_assignment_id,
                source_type="shipment", source_id=order_id, quantity_delta=3,
                actor_id=admin, created_at=now,
            ))
    return admin


@pytest.mark.parametrize("sort", ["updatedDesc", "priority", "shipDateAsc", "shipDateDesc"])
def test_source_order_page_batches_pending_ledger(test_database_engine: Engine, sort: str) -> None:
    admin = seed_source_orders(test_database_engine)
    service = OrderService(sessionmaker(test_database_engine, expire_on_commit=False))
    today = date(2026, 9, 30)
    with Session(test_database_engine) as session:
        expected = ordered_snapshots([
            service._snapshot(session, order, today)
            for order in session.scalars(select(Order))
        ], sort, today)
    counts = []
    for size in (10, 20):
        calls: list[str] = []

        def record(conn, cursor, statement, parameters, context, executemany, calls=calls):
            calls.append(statement)

        event.listen(test_database_engine, "before_cursor_execute", record)
        timings = []
        try:
            for _ in range(5):
                start = perf_counter()
                actual, total = service.list_visible(
                    actor_id=admin, include_drafts=True, sort_by=sort, today=today,
                    page=2, page_size=size,
                )
                timings.append((perf_counter() - start) * 1000)
                assert total == 40
                assert actual == expected[size:2 * size]
        finally:
            event.remove(test_database_engine, "before_cursor_execute", record)
        counts.append(len(calls) // 5)
        if sort.startswith("shipDate"):
            assert "quantity_ledger" not in calls[2]
        print(f"{sort} size={size} queries={counts[-1]} median_ms={median(timings):.2f}")
    assert counts == [8, 8]


def test_source_date_filter_and_status_match_snapshots(test_database_engine: Engine) -> None:
    admin = seed_source_orders(test_database_engine)
    service = OrderService(sessionmaker(test_database_engine, expire_on_commit=False))
    today = date(2026, 9, 30)
    with Session(test_database_engine) as session:
        snapshots = [service._snapshot(session, order, today)
                     for order in session.scalars(select(Order))]
    for start, end in [(date(2026, 9, 10), None), (None, date(2026, 9, 20)),
                       (date(2026, 9, 10), date(2026, 9, 20))]:
        for status in ["all", "草稿", "已逾期", "已完成"]:
            expected = ordered_snapshots([
                item for item in snapshots
                if (status == "all" or item.display_status == status)
                and any((start is None or value >= start) and (end is None or value <= end)
                        for value in item.contract_ship_dates)
            ], "priority", today)
            items, total = service.list_visible(
                actor_id=admin, include_drafts=True, today=today, status=status,
                ship_date_from=start, ship_date_to=end, page=2, page_size=5,
            )
            assert total == len(expected)
            assert items == expected[5:10]
