"""List compatibility and growth checks against the existing detail projection."""

import json
import subprocess
from datetime import date, datetime, timedelta
from time import perf_counter

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from app.api.shipments import ShipmentSummaryResponse, _draft_response
from app.db.models import (
    Order,
    OrderAssignment,
    OrderLine,
    Shipment,
    ShipmentBox,
    ShipmentBoxItem,
    ShipmentLine,
    ShipmentReceipt,
    ShipmentReceiptItem,
)
from app.main import create_app
from app.modules.identity_access import IdentityAccessService
from app.modules.shipments import ShipmentService
from tests.api.test_shipment_api import ADMIN_ID, FACTORY_IDS, USER_IDS, _seed


def seed_shipments(engine: Engine, count: int) -> None:
    assignment_id = _seed(engine)
    with Session(engine) as session, session.begin():
        assignment = session.get(OrderAssignment, assignment_id)
        assert assignment
        line = session.get(OrderLine, assignment.order_line_id)
        assert line
        order = session.get(Order, line.order_id)
        assert order
        for index in range(count):
            shipment = Shipment(
                shipment_id=f"list-{index:04}",
                shipment_no=f"发货{index}",
                factory_id=FACTORY_IDS[0],
                created_by=USER_IDS[0],
                status=["SHIPPED", "WITHDRAWN", "VOIDED", "VOID_PENDING"][index % 4],
                business_date=date(2026, 9, 1) + timedelta(days=index % 3),
                submitted_at=datetime(2026, 9, 1) + timedelta(seconds=index),
            )
            session.add(shipment)
            session.flush()
            # Multiple boxes must aggregate once and still deduplicate names.
            for box_no in [2, 1]:
                box = ShipmentBox(shipment_id=shipment.shipment_id, box_no=box_no)
                session.add(box)
                session.flush()
                session.add(
                    ShipmentBoxItem(
                        box_id=box.box_id,
                        order_assignment_id=assignment_id,
                        quantity=box_no + index,
                    )
                )
            session.add(
                ShipmentLine(
                    shipment_id=shipment.shipment_id,
                    order_assignment_id=assignment_id,
                    quantity=index * 2 + 3,
                    order_no_snapshot=order.order_no,
                    sku_id_snapshot=line.sku_id_snapshot,
                    product_name_snapshot=line.product_name_snapshot,
                    properties_value_snapshot=line.properties_value_snapshot,
                )
            )


def service(engine: Engine) -> ShipmentService:
    return ShipmentService(sessionmaker(engine, expire_on_commit=False))


def test_summary_matches_existing_details_and_receipt_quantity(
    test_database_engine: Engine,
) -> None:
    seed_shipments(test_database_engine, 13)
    with Session(test_database_engine) as session, session.begin():
        session.add(
            ShipmentReceipt(
                shipment_id="list-0000",
                status="CONFIRMED",
                version=1,
                saved_by=ADMIN_ID,
                saved_at=datetime(2026, 9, 1),
            )
        )
        session.flush()
        for item in session.scalars(
            select(ShipmentBoxItem).join(ShipmentBox).where(ShipmentBox.shipment_id == "list-0000")
        ):
            session.add(
                ShipmentReceiptItem(shipment_id="list-0000", box_item_id=item.item_id, quantity=0)
            )
        session.add(
            Shipment(
                shipment_id="draft-only",
                status="DRAFT",
                factory_id=FACTORY_IDS[1],
                created_by=USER_IDS[1],
            )
        )
        session.add(
            Shipment(
                shipment_id="deleted",
                shipment_no="deleted",
                status="SHIPPED",
                factory_id=FACTORY_IDS[1],
                created_by=USER_IDS[1],
                deleted_at=datetime(2026, 9, 1),
            )
        )
    reader = service(test_database_engine)
    old = reader.list_shipments()
    rows, total = reader.page_admin_shipments(page_size=100)
    assert total == 13
    for row in rows:
        detail = next(item for item in old if item.shipment_id == row["shipment_id"])
        assert row["order_nos"] == "、".join(dict.fromkeys(i.order_no for i in detail.lines))
        assert row["product_names"] == "、".join(
            dict.fromkeys(i.product_name for i in detail.lines)
        )
        assert row["total_quantity"] == detail.total_quantity
        assert row["status"] == detail.status
    assert next(r for r in rows if r["shipment_id"] == "list-0000")["total_quantity"] == 0
    assert reader.admin_shipment_factories() == ["S07接口工厂1"]
    assert len(reader.page_admin_shipments(page=2)[0]) == 3
    assert reader.page_admin_shipments(page=3) == ([], 13)
    assert reader.page_admin_shipments(keyword="S07-ORDER-A")[1] == 13
    assert reader.page_admin_shipments(keyword="%")[1] == 0
    assert reader.page_admin_shipments(keyword="_")[1] == 0
    assert reader.page_admin_shipments(keyword="接口测试产品")[1] == 0
    assert reader.page_admin_shipments(date_from=date(2026, 9, 3), date_to=date(2026, 9, 3))[1] == 4
    assert reader.page_admin_shipments(factory="S07接口工厂2")[1] == 0


@pytest.mark.parametrize(
    "sort_by",
    ["shipmentNo", "orderNos", "factory", "productNames", "totalQuantity", "businessDate"],
)
@pytest.mark.parametrize("direction", ["asc", "desc"])
def test_sort_matches_javascript_globally(
    test_database_engine: Engine,
    sort_by: str,
    direction: str,
) -> None:
    seed_shipments(test_database_engine, 23)
    reader = service(test_database_engine)
    source = reader.list_shipments()
    fields = {
        "shipmentNo": lambda s: s.shipment_no or "",
        "orderNos": lambda s: "、".join(dict.fromkeys(i.order_no for i in s.lines)) or "—",
        "factory": lambda s: s.factory_name or s.factory_id,
        "productNames": lambda s: "、".join(dict.fromkeys(i.product_name for i in s.lines)) or "—",
        "totalQuantity": lambda s: str(s.total_quantity),
        "businessDate": lambda s: str(s.business_date or ""),
    }
    data = [{"id": s.shipment_id, "value": fields[sort_by](s)} for s in source]
    expected = json.loads(
        subprocess.check_output(
            [
                "node",
                "-e",
                """
      let data = JSON.parse(process.argv[1]);
      data.sort((a,b) => a.value.localeCompare(b.value, 'zh-CN', {numeric:true})
        * (process.argv[2] === 'desc' ? -1 : 1));
      process.stdout.write(JSON.stringify(data.map(x=>x.id)));
    """,
                json.dumps(data),
                direction,
            ],
            text=True,
        )
    )
    rows, total = reader.page_admin_shipments(sort_by=sort_by, sort_order=direction, page=2)
    assert total == 23
    assert [r["shipment_id"] for r in rows] == expected[10:20]


@pytest.mark.parametrize("count", [20, 100])
def test_query_growth_and_payload(test_database_engine: Engine, count: int) -> None:
    seed_shipments(test_database_engine, count)
    reader = service(test_database_engine)
    calls: list[str] = []

    def record(_conn, _cursor, statement, _params, _context, _many):  # type: ignore[no-untyped-def]
        calls.append(statement)

    event.listen(test_database_engine, "before_cursor_execute", record)
    try:
        start = perf_counter()
        old = reader.list_shipments()
        old_ms = (perf_counter() - start) * 1000
        old_queries = len(calls)
        calls.clear()
        start = perf_counter()
        rows, total = reader.page_admin_shipments(page=2)
        new_ms = (perf_counter() - start) * 1000
        assert len(calls) == 2
        assert len(rows) == 10 and total == count
        assert not any("shipment_files" in sql or "audit_logs" in sql for sql in calls)
        old_bytes = len(
            json.dumps(
                [_draft_response(s).model_dump(mode="json", by_alias=True) for s in old],
                ensure_ascii=False,
            ).encode()
        )
        new_bytes = len(
            json.dumps(
                [
                    ShipmentSummaryResponse.model_validate(r).model_dump(mode="json", by_alias=True)
                    for r in rows
                ],
                ensure_ascii=False,
            ).encode()
        )
        assert new_bytes < old_bytes
        print(
            f"count={count}: detail SQL={old_queries}, summary SQL={len(calls)}, "
            f"detail_ms={old_ms:.1f}, summary_ms={new_ms:.1f}, "
            f"detail_json_bytes={old_bytes}, summary_bytes={new_bytes}"
        )
    finally:
        event.remove(test_database_engine, "before_cursor_execute", record)


def test_summary_api_requires_admin(test_database_engine: Engine, test_database_url: str) -> None:
    seed_shipments(test_database_engine, 12)
    identity = IdentityAccessService(
        sessionmaker(test_database_engine, expire_on_commit=False),
        token_secret=b"list-token",
        phone_encryption_secret=b"list-encryption",
        phone_digest_secret=b"list-digest",
    )
    with TestClient(
        create_app(database_url=test_database_url, identity_service=identity)
    ) as client:
        for path in ["/summary", "/factory-options"]:
            assert client.get("/api/v1/admin/shipments" + path).status_code == 401
        factory = identity.issue_session(user_id=USER_IDS[0], terminal="mini")
        client.headers["Authorization"] = f"Bearer {factory.access_token}"
        assert client.get("/api/v1/admin/shipments/summary").status_code == 403
        admin = identity.issue_session(user_id=ADMIN_ID, terminal="mini")
        client.headers["Authorization"] = f"Bearer {admin.access_token}"
        result = client.get("/api/v1/admin/shipments/summary?page=2").json()
        assert result["total"] == 12 and len(result["items"]) == 2
        assert "boxes" not in result["items"][0]
        assert client.get("/api/v1/admin/shipments/summary?sortBy=evil").status_code == 422
        assert client.get("/api/v1/admin/shipments/summary?page=0").status_code == 422
        assert client.get("/api/v1/admin/shipments/factory-options").json()["items"] == [
            "S07接口工厂1"
        ]
        # The old API remains a full detail API for other callers.
        assert "boxes" in client.get("/api/v1/admin/shipments").json()["items"][0]


def test_long_mult_order_summary_preserves_full_first_occurrence_sort(
    test_database_engine: Engine,
) -> None:
    seed_shipments(test_database_engine, 2)
    with Session(test_database_engine) as session, session.begin():
        original = session.scalar(select(OrderLine))
        assert original
        for index in range(9):
            order = Order(
                order_id=f"long-{index}",
                order_no=f"关联{index}" + "X" * 90,
                source="manual",
                tracker="",
                lifecycle="PUBLISHED",
                version=1,
                created_by=ADMIN_ID,
                updated_by=ADMIN_ID,
            )
            session.add(order)
            session.flush()
            name = f"产品{index}" + "甲" * 230 if index < 7 else f"末尾{[10, 2][index - 7]}"
            line = OrderLine(
                order_id=order.order_id,
                product_variant_id=original.product_variant_id,
                order_quantity=100,
                sku_id_snapshot=original.sku_id_snapshot,
                product_name_snapshot=name,
                properties_value_snapshot="",
            )
            session.add(line)
            session.flush()
            assignment = OrderAssignment(
                order_line_id=line.order_line_id,
                factory_id=FACTORY_IDS[0],
                assigned_quantity=100,
                factory_name_snapshot="S07接口工厂1",
                contract_ship_date=date(2026, 9, 1),
            )
            session.add(assignment)
            session.flush()
            for target in range(2):
                if index >= 7 and index != 7 + target:
                    continue
                # Deliberately insert in box 2 then 1; first occurrence uses box number.
                for box in session.scalars(
                    select(ShipmentBox)
                    .where(ShipmentBox.shipment_id == f"list-{target:04}")
                    .order_by(ShipmentBox.box_no.desc())
                ):
                    session.add(
                        ShipmentBoxItem(
                            box_id=box.box_id,
                            order_assignment_id=assignment.order_assignment_id,
                            quantity=3,
                        )
                    )
                session.add(
                    ShipmentLine(
                        shipment_id=f"list-{target:04}",
                        order_assignment_id=assignment.order_assignment_id,
                        quantity=6,
                        order_no_snapshot=order.order_no,
                        sku_id_snapshot=line.sku_id_snapshot,
                        product_name_snapshot=name,
                        properties_value_snapshot="",
                    )
                )
    reader = service(test_database_engine)
    old = reader.list_shipments()
    for sort in ["orderNos", "productNames"]:
        result, total = reader.page_admin_shipments(sort_by=sort, page_size=100)
        assert total == 2
        for row in result:
            detail = next(s for s in old if s.shipment_id == row["shipment_id"])
            assert row["product_names"] == "、".join(
                dict.fromkeys(line.product_name for line in detail.lines)
            )
            assert row["order_nos"] == "、".join(
                dict.fromkeys(line.order_no for line in detail.lines)
            )
            assert row["total_quantity"] == detail.total_quantity
            assert len(row["product_names"]) > 1500
    first, total = reader.page_admin_shipments(sort_by="productNames", page_size=1)
    assert first[0]["shipment_id"] == "list-0001"
    assert total == 2
    # This term is only present near the end of the complete concatenated summary.
    assert reader.page_admin_shipments(keyword="关联8")[1] == 1


@pytest.mark.parametrize("count", [20, 100])
def test_local_api_performance_evidence(
    test_database_engine: Engine,
    test_database_url: str,
    count: int,
) -> None:
    seed_shipments(test_database_engine, count)
    identity = IdentityAccessService(
        sessionmaker(test_database_engine, expire_on_commit=False),
        token_secret=b"list-token",
        phone_encryption_secret=b"list-encryption",
        phone_digest_secret=b"list-digest",
    )
    admin = identity.issue_session(user_id=ADMIN_ID, terminal="mini")
    app = create_app(
        database_url=test_database_url,
        identity_service=identity,
        shipment_service=service(test_database_engine),
    )
    with TestClient(app) as client:
        client.headers["Authorization"] = f"Bearer {admin.access_token}"
        for path in ["", "/summary?page=2", "/summary?page=2&sortBy=productNames"]:
            start = perf_counter()
            result = client.get("/api/v1/admin/shipments" + path)
            duration = (perf_counter() - start) * 1000
            assert result.status_code == 200
            print(
                f"API count={count}, path={path or 'detail-list'}, "
                f"ms={duration:.1f}, bytes={len(result.content)}"
            )


def test_factory_options_include_records_outside_current_page(test_database_engine: Engine) -> None:
    seed_shipments(test_database_engine, 12)
    with Session(test_database_engine) as session, session.begin():
        session.add(
            Shipment(
                shipment_id="off-page",
                shipment_no="OTHER",
                status="VOIDED",
                factory_id=FACTORY_IDS[1],
                created_by=USER_IDS[1],
                business_date=date(2020, 1, 1),
            )
        )
    reader = service(test_database_engine)
    rows, total = reader.page_admin_shipments()
    assert total == 13
    assert all(r["factory_id"] == FACTORY_IDS[0] for r in rows)
    assert set(reader.admin_shipment_factories()) == {"S07接口工厂1", "S07接口工厂2"}
    rows, total = reader.page_admin_shipments(factory="S07接口工厂2")
    assert total == 1 and rows[0]["shipment_id"] == "off-page"
    assert rows[0]["order_nos"] == rows[0]["product_names"] == "—"
    assert rows[0]["total_quantity"] == 0


def test_multiple_factories_filter_before_count_and_page(
    test_database_engine: Engine, test_database_url: str,
) -> None:
    seed_shipments(test_database_engine, 12)
    with Session(test_database_engine) as session, session.begin():
        session.get(Shipment, "list-0000").factory_id = FACTORY_IDS[1]
    identity = IdentityAccessService(
        sessionmaker(test_database_engine, expire_on_commit=False),
        token_secret=b"list-token", phone_encryption_secret=b"list-encryption",
        phone_digest_secret=b"list-digest",
    )
    admin = identity.issue_session(user_id=ADMIN_ID, terminal="mini")
    with TestClient(
        create_app(database_url=test_database_url, identity_service=identity)
    ) as client:
        client.headers["Authorization"] = f"Bearer {admin.access_token}"
        path = "/api/v1/admin/shipments/summary"
        result = client.get(path, params=[("factories", "S07接口工厂2")]).json()
        assert result["total"] == 1
        assert result["items"][0]["shipmentId"] == "list-0000"
        params = [("factories", "S07接口工厂1"), ("factories", "S07接口工厂2"),
                  ("factories", "S07接口工厂1"), ("sortBy", "shipmentNo"), ("page", "2")]
        result = client.get(path, params=params).json()
        assert result["total"] == 12
        assert [r["shipmentId"] for r in result["items"]] == ["list-0010", "list-0011"]
        result = client.get(path, params=params[:3] + [("dateFrom", "2026-09-03"),
                                                     ("keyword", "发货")]).json()
        assert result["total"] == 4
        assert client.get(path, params={"factory": "S07接口工厂2"}).json()["total"] == 1
        assert client.get(path, params={"factory": "S07接口工厂2",
                                      "factories": "S07接口工厂1"}).json()["total"] == 12
        assert client.get(path, params={"factories": "%"}).json()["total"] == 0
