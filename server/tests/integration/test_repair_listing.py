import json
from dataclasses import asdict
from datetime import date, datetime
from time import perf_counter

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Factory, RepairInspectionLine, RepairOrder
from app.main import create_app
from app.modules.identity_access import IdentityAccessService
from app.modules.repairs.confirmation import RepairConfirmationService
from app.modules.repairs.listing import RepairListingService
from app.modules.repairs.returns import RepairReturnLineInput, RepairReturnService
from tests.integration.test_repair_returns import seed_return_repair


def test_summary_matches_detail_after_multiple_inspections_and_batches(
    test_database_engine: Engine,
):
    seed_return_repair(test_database_engine)
    sessions = sessionmaker(test_database_engine, expire_on_commit=False)
    with sessions.begin() as session:
        original = session.scalar(select(RepairInspectionLine))
        original.warehouse_return_quantity = 6
        session.add(
            RepairInspectionLine(
                repair_id="return-repair",
                source_sheet="Sheet1",
                source_row=3,
                source_order=2,
                box_number="2",
                product_id="return-product",
                variant_id="return-variant",
                source_sku_id="RETURN-SKU",
                source_product_id="RETURN-PRODUCT",
                product_name="返修测试产品",
                properties_value="返修规格",
                warehouse_return_quantity=6,
            )
        )
    service = RepairReturnService(sessions)
    listing = RepairListingService(sessions)
    for index, (repaired, scrapped) in enumerate([(3, 2), (5, 2)]):
        detail = service.submit(
            repair_id="return-repair",
            factory_id="return-factory",
            submitted_by="return-factory-user",
            idempotency_key=f"batch{index}",
            lines=(RepairReturnLineInput("return-variant", repaired, scrapped),),
        )
        rows, total = listing.page()
        assert total == 1
        assert rows[0] == {key: getattr(detail, key) for key in rows[0]}
        assert rows[0]["returned_quantity"] == (5 if index == 0 else 12)
    assert rows[0]["status"] == "COMPLETED"
    service.archive(
        repair_id="return-repair", archived_by="return-admin", idempotency_key="archive"
    )
    assert listing.page() == ([], 0)
    assert listing.factories() == []


def seed_many(engine: Engine, count: int):
    seed_return_repair(engine)
    with Session(engine) as session, session.begin():
        session.add(
            Factory(
                factory_id="other", supplier_number="OTHER", factory_name="阿厂2", is_enabled=False
            )
        )
        session.flush()
        for index in range(count - 1):
            session.add(
                RepairOrder(
                    repair_id=f"repair{index}",
                    repair_no=f"FX20260828-{index:03}",
                    factory_id="other" if index % 2 else "return-factory",
                    status="COMPLETED" if index % 3 == 0 else "INCOMPLETE",
                    warehouse_return_quantity=12,
                    repaired_quantity=10 if index % 3 == 0 else 0,
                    scrapped_quantity=2 if index % 3 == 0 else 0,
                    returned_quantity=12 if index % 3 == 0 else 0,
                    return_date=date(2026, 8, 28),
                    original_file_id=9501,
                    source_sha256=f"{index:064x}",
                    created_by="return-admin",
                )
            )


@pytest.mark.parametrize("count", [20, 100])
def test_pagination_queries_payload_and_timing(
    test_database_engine: Engine, test_database_url: str, count: int
):
    seed_many(test_database_engine, count)
    sessions = sessionmaker(test_database_engine, expire_on_commit=False)
    listing = RepairListingService(sessions)
    old = RepairConfirmationService(sessions)
    statements = []

    def record(*args):
        statements.append(args[2])

    event.listen(test_database_engine, "before_cursor_execute", record)
    try:
        start = perf_counter()
        full = old.list_all()
        old_ms = (perf_counter() - start) * 1000
        old_count = len(statements)
        statements.clear()
        start = perf_counter()
        rows, total = listing.page(page=2)
        new_ms = (perf_counter() - start) * 1000
        assert len(statements) == 2
        assert total == count
        assert [row["repair_id"] for row in rows] == [item.repair_id for item in full[10:20]]
        assert all("repair_inspection_lines" not in sql for sql in statements)
        assert "LIMIT" in statements[-1]
        old_bytes = len(json.dumps([asdict(item) for item in full], default=str).encode())
        new_bytes = len(json.dumps(rows, default=str).encode())
        print(
            f"repair count={count} SQL {old_count}->2 bytes {old_bytes}->{new_bytes} "
            f"ms {old_ms:.2f}->{new_ms:.2f}"
        )
        assert new_bytes < old_bytes
    finally:
        event.remove(test_database_engine, "before_cursor_execute", record)

    identity = IdentityAccessService(
        sessions,
        token_secret=b"repair-listing-timing",
        phone_encryption_secret=b"repair-timing-encryption",
        phone_digest_secret=b"repair-timing-digest",
    )
    web = identity.issue_session(user_id="return-admin", terminal="web")
    app = create_app(database_url=test_database_url, identity_service=identity)
    with TestClient(app, base_url="https://testserver") as client:
        client.cookies.set("ot_web_session", web.access_token)
        start = perf_counter()
        old_response = client.get("/api/v1/admin/repairs?pageSize=100")
        old_api_ms = (perf_counter() - start) * 1000
        start = perf_counter()
        new_response = client.get("/api/v1/admin/repairs/summary?pageSize=10")
        new_api_ms = (perf_counter() - start) * 1000
        assert old_response.status_code == new_response.status_code == 200
        assert new_response.json()["total"] == old_response.json()["total"] == count
        assert len(new_response.content) < len(old_response.content)
        print(
            f"repair API count={count} bytes {len(old_response.content)}"
            f"->{len(new_response.content)} ms {old_api_ms:.2f}->{new_api_ms:.2f}"
        )


def test_filters_and_all_numeric_sorts_use_global_rows(test_database_engine: Engine):
    seed_many(test_database_engine, 25)
    listing = RepairListingService(sessionmaker(test_database_engine))
    rows, total = listing.page(
        factories=["阿厂2"],
        status="COMPLETED",
        return_from=date(2026, 8, 28),
        return_to=date(2026, 8, 28),
        page_size=100,
    )
    assert total == 4
    assert all(row["factory_name"] == "阿厂2" for row in rows)
    assert set(listing.factories()) == {"返修测试工厂", "阿厂2"}
    assert listing.page(keyword="%")[1] == 0
    assert listing.page(keyword="_")[1] == 0
    assert listing.page(keyword="fx20260828")[1] == 24
    assert listing.page(factories=["阿厂"])[1] == 0
    base, _ = listing.page(page_size=100)
    for field, attr in [
        ("repairedQuantity", "repaired_quantity"),
        ("scrappedQuantity", "scrapped_quantity"),
        ("returnedQuantity", "returned_quantity"),
        ("warehouseReturnQuantity", "warehouse_return_quantity"),
        ("returnDate", "return_date"),
        ("status", "status"),
    ]:
        for direction in ["asc", "desc"]:
            expected = sorted(base, key=lambda row: row[attr], reverse=direction == "desc")
            actual, total = listing.page(sort_by=field, sort_order=direction, page=2)
            assert total == 25
            assert actual == expected[10:20]
    with Session(test_database_engine) as session, session.begin():
        row = session.get(RepairOrder, "repair0")
        row.archived_at = datetime(2026, 9, 1)
    assert listing.page(page_size=100)[1] == 24


def test_summary_api_is_web_admin_only_and_preserves_detail_contract(
    test_database_engine: Engine, test_database_url: str
):
    seed_return_repair(test_database_engine)
    sessions = sessionmaker(test_database_engine, expire_on_commit=False)
    identity = IdentityAccessService(
        sessions,
        token_secret=b"repair-listing-test",
        phone_encryption_secret=b"repair-list-encryption",
        phone_digest_secret=b"repair-list-digest",
    )
    web = identity.issue_session(user_id="return-admin", terminal="web")
    mini = identity.issue_session(user_id="return-factory-user", terminal="mini")
    app = create_app(database_url=test_database_url, identity_service=identity)
    with TestClient(app, base_url="https://testserver") as client:
        assert client.get("/api/v1/admin/repairs/summary").status_code == 401
        assert (
            client.get(
                "/api/v1/admin/repairs/summary",
                headers={"Authorization": f"Bearer {mini.access_token}"},
            ).status_code
            == 401
        )
        client.cookies.set("ot_web_session", web.access_token)
        response = client.get("/api/v1/admin/repairs/summary")
        assert response.status_code == 200
        assert "lines" not in response.json()["items"][0]
        assert client.get("/api/v1/admin/repairs/factory-options").json() == {
            "items": ["返修测试工厂"]
        }
        assert "lines" in client.get("/api/v1/admin/repairs").json()["items"][0]
        assert "lines" in client.get("/api/v1/admin/repairs/return-repair").json()


def test_chinese_numeric_string_sort_is_global_and_stable(test_database_engine: Engine):
    seed_many(test_database_engine, 25)
    sessions = sessionmaker(test_database_engine)
    with sessions.begin() as session:
        extra = ["阿厂10", "阿厂02", "博厂2", "博厂10", "宇婷", "中厂"]
        for index, name in enumerate(extra):
            session.add(
                Factory(
                    factory_id=f"sort{index}",
                    supplier_number=f"S{index}",
                    factory_name=name,
                    is_enabled=True,
                )
            )
        session.flush()
        for index in range(24):
            repair = session.get(RepairOrder, f"repair{index}")
            repair.factory_id = f"sort{index % len(extra)}"
            repair.repair_no = f"FX20260828-{index + 1}"
    listing = RepairListingService(sessions)
    base, _ = listing.page(page_size=100)
    names = {
        name: index
        for index, name in enumerate(
            ["阿厂02", "阿厂10", "博厂2", "博厂10", "返修测试工厂", "宇婷", "中厂"]
        )
    }
    for field in ["factoryName", "repairNo"]:
        for direction in ["asc", "desc"]:

            def key(row, field=field):
                return (
                    names[row["factory_name"]]
                    if field == "factoryName"
                    else (row["repair_no"].split("-")[0], int(row["repair_no"].split("-")[1]))
                )

            expected = sorted(base, key=key, reverse=direction == "desc")
            actual = []
            for page in [1, 2, 3]:
                rows, total = listing.page(sort_by=field, sort_order=direction, page=page)
                assert total == 25
                actual.extend(rows)
            assert actual == expected
