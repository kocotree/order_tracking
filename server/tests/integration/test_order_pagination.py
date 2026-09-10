from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import (
    Order,
    OrderAssignment,
    OrderLine,
    ProductVariant,
    QuantityLedger,
    Shipment,
)
from app.main import create_app
from app.modules.identity_access import IdentityAccessService
from app.modules.orders import AssignmentInput, DraftLineInput, OrderService
from tests.integration.test_order_lifecycle import _seed_order_dependencies


@pytest.mark.parametrize("factory_scope", [False, True])
def test_admin_pagination_matches_complete_snapshots_and_bounds_queries(
    test_database_engine: Engine,
    factory_scope: bool,
) -> None:
    admin, factory, factory_b, variant = _seed_order_dependencies(test_database_engine)
    service = OrderService(sessionmaker(test_database_engine, expire_on_commit=False))
    for index in range(25):
        service.create_draft(
            actor_id=admin,
            order_no=f"O{index}",
            order_date=date(2026, 8, 1),
            tracker="松子",
            request_id=f"seed{index}",
            lines=[
                DraftLineInput(
                    variant_id=variant,
                    order_quantity=40,
                    assignments=[
                        AssignmentInput(
                            factory_id=factory,
                            quantity=40,
                            contract_ship_date=date(2026, 8, index + 1),
                        )
                    ],
                )
            ],
        )
    with Session(test_database_engine) as session, session.begin():
        orders = list(session.scalars(select(Order).order_by(Order.order_no)))
        for index, item in enumerate(orders):
            item.lifecycle = ["DRAFT", "PUBLISHED", "COMPLETED"][index % 3]
            item.order_date = None if index % 5 == 0 else date(2026, 8, index + 1)
            item.tracker = ["松子", "烧麦", "橄榄"][index % 3]
            line = session.scalar(select(OrderLine).where(OrderLine.order_id == item.order_id))
            assert line is not None
            line.product_name_snapshot = ["帽2", "帽10", "甲", "a", "A", "ß", "尾 "][index % 7]
            line.category_snapshot = ["童装春夏", "童帽秋冬", None, ""][index % 4]
            assignment = session.scalar(
                select(OrderAssignment).where(OrderAssignment.order_line_id == line.order_line_id)
            )
            assert assignment is not None
            for number, delta in enumerate([30, -5, -21] if index % 5 else [50, -5, -1]):
                session.add(
                    QuantityLedger(
                        order_assignment_id=assignment.order_assignment_id,
                        source_type=["shipment", "shipment_receipt", "shipment_return"][number],
                        source_id=f"ledger-{index}-{number}",
                        quantity_delta=delta,
                        actor_id=admin,
                        created_at=datetime(2026, 9, 1),
                    )
                )
            assignment.initial_shipped_quantity = index % 20
            if index in {1, 3}:
                line.order_quantity = 2_000_000_000
                assignment.assigned_quantity = 2_000_000_000
                assignment.initial_shipped_quantity = 9_999_997 if index == 1 else 9_999_996
            assignment.contract_ship_date = None if index % 4 == 0 else date(2026, 8, 1)
            assignment.factory_name_snapshot = ["厂2", "厂10", "甲", "乙"][index % 4]
            if index % 2 == 0:
                assignment.assigned_quantity = 20
                session.add(
                    OrderAssignment(
                        order_line_id=line.order_line_id,
                        factory_id=factory_b,
                        assigned_quantity=20,
                        initial_shipped_quantity=index % 5,
                        factory_name_snapshot="另一工厂",
                        contract_ship_date=date(2026, 10, 1),
                    )
                )
    actor_id = "factory-user-a" if factory_scope else admin
    today = date(2026, 9, 9)
    with Session(test_database_engine) as session:
        expected = [
            service._snapshot(session, item, today, factory_id=factory if factory_scope else None)
            for item in session.scalars(select(Order))
            if not factory_scope or item.lifecycle != "DRAFT"
        ]
    for sort in ["priority", "updatedDesc", "orderDateDesc", "shipDateAsc", "shipDateDesc"] + [
        field + direction
        for field in [
            "orderNo",
            "productName",
            "category",
            "tracker",
            "factory",
            "contractShipDate",
            "progressPercent",
            "shippedQuantity",
            "status",
        ]
        for direction in ["Asc", "Desc"]
    ]:
        reverse = sort.endswith("Desc") and sort not in {
            "updatedDesc",
            "orderDateDesc",
            "shipDateDesc",
            "contractShipDateDesc",
        }
        ordered = sorted(expected, key=service._sort_key(sort, today), reverse=reverse)
        calls = []

        def count(*args, calls=calls):
            calls.append(args[2])

        event.listen(test_database_engine, "before_cursor_execute", count)
        try:
            actual, total = service.list_visible(
                actor_id=actor_id,
                include_drafts=True,
                sort_by=sort,
                page=2,
                page_size=10,
                today=today,
            )
        finally:
            event.remove(test_database_engine, "before_cursor_execute", count)
        assert actual == ordered[10:20], sort
        assert total == len(expected)
        assert len(calls) <= 6, (sort, len(calls))

    for status in ["all", "草稿", "未完成", "已逾期", "已完成"]:
        for start, end in [
            (None, None),
            (date(2026, 9, 1), None),
            (None, date(2026, 8, 15)),
            (date(2026, 8, 5), date(2026, 9, 1)),
        ]:
            matching = [
                item
                for item in expected
                if (status == "all" or item.display_status == status)
                and (
                    not (start or end)
                    or any(
                        (start is None or value >= start) and (end is None or value <= end)
                        for value in item.contract_ship_dates
                    )
                )
            ]
            matching.sort(key=service._sort_key("priority", today))
            actual, total = service.list_visible(
                actor_id=actor_id,
                include_drafts=True,
                status=status,
                ship_date_from=start,
                ship_date_to=end,
                today=today,
                page_size=10,
            )
            assert actual == matching[:10]
            assert total == len(matching)
    actual, total = service.list_visible(
        actor_id=actor_id,
        include_drafts=True,
        factory_ids=[factory, factory_b],
        today=today,
        page=2,
        page_size=10,
    )
    assert total == len(expected)
    assert actual == sorted(expected, key=service._sort_key("priority", today))[10:20]


def test_dashboard_counts_all_orders_and_beijing_business_day(
    test_database_engine: Engine,
    test_database_url: str,
) -> None:
    admin, factory, _, _ = _seed_order_dependencies(test_database_engine)
    with Session(test_database_engine) as session, session.begin():
        for index in range(105):
            order = Order(
                order_id=f"bulk-{index}",
                order_no=f"B{index}",
                source="manual",
                tracker="松子",
                lifecycle="PUBLISHED",
                created_by=admin,
                updated_by=admin,
            )
            session.add(order)
            session.flush()
            line = OrderLine(
                order_id=order.order_id,
                product_variant_id="variant-order-1",
                order_quantity=10,
                sku_id_snapshot="SKU",
                product_name_snapshot="帽子",
                properties_value_snapshot="红色",
            )
            session.add(line)
            session.flush()
            session.add(
                OrderAssignment(
                    order_line_id=line.order_line_id,
                    factory_id=factory,
                    assigned_quantity=10,
                    initial_shipped_quantity=0,
                    factory_name_snapshot="甲",
                    contract_ship_date=date(2026, 9, 8),
                )
            )
        for index, (status, business_date, deleted) in enumerate(
            [
                ("SHIPPED", date(2026, 9, 9), False),
                ("VOID_PENDING", date(2026, 9, 9), False),
                ("WITHDRAWN", date(2026, 9, 9), False),
                ("VOIDED", date(2026, 9, 9), False),
                ("DRAFT", date(2026, 9, 9), False),
                ("SHIPPED", date(2026, 9, 8), False),
                ("SHIPPED", date(2026, 9, 9), True),
            ]
        ):
            session.add(
                Shipment(
                    shipment_id=f"ship-{index}",
                    shipment_no=f"S{index}",
                    factory_id=factory,
                    status=status,
                    business_date=business_date,
                    created_by=admin,
                    deleted_at=datetime(2026, 9, 9) if deleted else None,
                )
            )
    service = OrderService(
        sessionmaker(test_database_engine, expire_on_commit=False),
        clock=lambda: datetime(2026, 9, 8, 16, tzinfo=UTC),
    )
    assert service.dashboard_counts(actor_id=admin) == (105, 2)
    previous = OrderService(
        sessionmaker(test_database_engine, expire_on_commit=False),
        clock=lambda: datetime(2026, 9, 8, 15, 59, 59, tzinfo=UTC),
    )
    assert previous.dashboard_counts(actor_id=admin) == (0, 1)
    recent, total = service.list_visible(actor_id=admin, page_size=10, sort_by="updatedDesc")
    assert len(recent) == 10
    assert total == 105
    identity = IdentityAccessService(
        sessionmaker(test_database_engine, expire_on_commit=False),
        token_secret=b"pagination-test-token",
        phone_encryption_secret=b"pagination-test-phone",
        phone_digest_secret=b"pagination-test-digest",
    )
    login = identity.issue_session(user_id=admin, terminal="web")
    app = create_app(
        database_url=test_database_url, identity_service=identity, order_service=service
    )
    with TestClient(app, base_url="https://testserver") as client:
        client.cookies.set("ot_web_session", login.access_token)
        response = client.get("/api/v1/admin/dashboard/orders")
        assert response.status_code == 200
        payload = response.json()
        assert payload["overdueOrders"] == 105
        assert payload["todayShipments"] == 2
        assert len(payload["recentOrders"]) == 10


def test_long_summary_sort_empty_orders_and_last_factory_name(test_database_engine: Engine) -> None:
    admin, factory, factory_b, _ = _seed_order_dependencies(test_database_engine)
    with Session(test_database_engine) as session, session.begin():
        template = session.get(ProductVariant, "variant-order-1")
        assert template is not None
        variants = []
        for index in range(24):
            variant = ProductVariant(
                variant_id=f"v{index}",
                product_id=template.product_id,
                source_sku_id=f"s{index}",
                properties_value="",
                is_available=True,
                source_modified_at=template.source_modified_at,
                first_synced_at=template.first_synced_at,
                last_synced_at=template.last_synced_at,
            )
            session.add(variant)
            variants.append(variant)
        session.flush()
        for order_id in ["empty", "long-a", "long-b"]:
            session.add(
                Order(
                    order_id=order_id,
                    order_no=order_id,
                    source="manual",
                    tracker="松子",
                    lifecycle="DRAFT",
                    created_by=admin,
                    updated_by=admin,
                )
            )
            session.flush()
            if order_id == "empty":
                continue
            for index, variant in enumerate(variants):
                suffix = "Z" if order_id == "long-a" else "A"
                name = "相同长产品" * 40 if index < 23 else suffix
                line = OrderLine(
                    order_id=order_id,
                    product_variant_id=variant.variant_id,
                    order_quantity=40,
                    sku_id_snapshot=variant.source_sku_id,
                    product_name_snapshot=name,
                    properties_value_snapshot="",
                    category_snapshot="童装春夏",
                )
                session.add(line)
                session.flush()
                for factory_id in [factory_b, factory]:
                    session.add(
                        OrderAssignment(
                            order_line_id=line.order_line_id,
                            factory_id=factory_id,
                            assigned_quantity=20,
                            initial_shipped_quantity=0,
                            factory_name_snapshot=suffix if index == 23 else "旧名",
                            contract_ship_date=None,
                        )
                    )
    service = OrderService(sessionmaker(test_database_engine, expire_on_commit=False))
    today = date(2026, 9, 9)
    with Session(test_database_engine) as session:
        expected = [
            service._snapshot(session, item, today) for item in session.scalars(select(Order))
        ]
    for field in ["productName", "factory", "category", "progressPercent", "contractShipDate"]:
        for direction in ["Asc", "Desc"]:
            sort = field + direction
            reverse = direction == "Desc" and field != "contractShipDate"
            ordered = sorted(expected, key=service._sort_key(sort, today), reverse=reverse)
            actual, total = service.list_visible(
                actor_id=admin, include_drafts=True, sort_by=sort, page=2, page_size=1, today=today
            )
            assert actual == ordered[1:2], sort
            assert total == 3


def test_factory_keyword_and_category_only_match_visible_lines(
    test_database_engine: Engine,
) -> None:
    admin, factory, other, variant = _seed_order_dependencies(test_database_engine)
    service = OrderService(sessionmaker(test_database_engine, expire_on_commit=False))
    draft = service.create_draft(
        actor_id=admin,
        order_no="scoped",
        order_date=date(2026, 9, 1),
        tracker="松子",
        request_id="scoped",
        lines=[
            DraftLineInput(
                variant_id=variant,
                order_quantity=10,
                assignments=[
                    AssignmentInput(
                        factory_id=factory, quantity=10, contract_ship_date=date(2026, 9, 30)
                    )
                ],
            )
        ],
    )
    with Session(test_database_engine) as session, session.begin():
        order = session.get(Order, draft.order_id)
        order.lifecycle = "PUBLISHED"
        own = session.scalar(select(OrderLine).where(OrderLine.order_id == order.order_id))
        own.product_name_snapshot = "own hat"
        own.category_snapshot = "童帽春夏"
        template = session.get(ProductVariant, variant)
        session.add(
            ProductVariant(
                variant_id="hidden-variant",
                product_id=template.product_id,
                source_sku_id="hidden",
                properties_value="hidden",
                is_available=True,
                source_modified_at=template.source_modified_at,
                first_synced_at=template.first_synced_at,
                last_synced_at=template.last_synced_at,
            )
        )
        session.flush()
        hidden = OrderLine(
            order_id=order.order_id,
            product_variant_id="hidden-variant",
            order_quantity=10,
            sku_id_snapshot="hidden",
            product_name_snapshot="secret clothing",
            properties_value_snapshot="hidden",
            category_snapshot="童装春夏",
        )
        session.add(hidden)
        session.flush()
        session.add(
            OrderAssignment(
                order_line_id=hidden.order_line_id,
                factory_id=other,
                assigned_quantity=10,
                initial_shipped_quantity=0,
                factory_name_snapshot="other",
                contract_ship_date=date(2020, 1, 1),
            )
        )
    assert service.list_visible(actor_id="factory-user-a", keyword="secret")[1] == 0
    assert service.list_visible(actor_id="factory-user-a", category="服装")[1] == 0
    items, total = service.list_visible(
        actor_id="factory-user-a", keyword="own", category="帽子", today=date(2026, 9, 10)
    )
    assert total == 1 and len(items[0].lines) == 1
    assert items[0].display_status == "未完成"
    assert items[0].contract_ship_dates == [date(2026, 9, 30)]
    assert service.list_visible(actor_id=admin, keyword="secret", category="服装")[1] == 1
