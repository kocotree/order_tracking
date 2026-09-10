from datetime import date, datetime

from fastapi.testclient import TestClient
from sqlalchemy import Engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import (
    Shipment,
    ShipmentBox,
    ShipmentBoxItem,
    ShipmentReceipt,
    ShipmentReceiptItem,
)
from app.main import create_app
from app.modules.identity_access import IdentityAccessService
from tests.api.test_shipment_api import ADMIN_ID, FACTORY_IDS, USER_IDS
from tests.api.test_shipment_summary import seed_shipments, service


def test_factory_pages_match_details_and_apply_full_scope_filters(
    test_database_engine: Engine,
) -> None:
    seed_shipments(test_database_engine, 43)
    with Session(test_database_engine) as session, session.begin():
        session.add_all(
            [
                Shipment(
                    shipment_id="other",
                    status="SHIPPED",
                    factory_id=FACTORY_IDS[1],
                    created_by=USER_IDS[1],
                    shipment_no="other",
                ),
                Shipment(
                    shipment_id="draft",
                    status="DRAFT",
                    factory_id=FACTORY_IDS[0],
                    created_by=USER_IDS[0],
                ),
                Shipment(
                    shipment_id="deleted",
                    status="SHIPPED",
                    factory_id=FACTORY_IDS[0],
                    created_by=USER_IDS[0],
                    deleted_at=datetime(2026, 9, 1),
                ),
                Shipment(
                    shipment_id="edit",
                    status="DRAFT",
                    factory_id=FACTORY_IDS[0],
                    created_by=USER_IDS[0],
                    source_shipment_id="list-0001",
                ),
                ShipmentReceipt(
                    shipment_id="list-0000",
                    status="CONFIRMED",
                    version=1,
                    saved_by=ADMIN_ID,
                    saved_at=datetime(2026, 9, 1),
                ),
            ]
        )
        session.flush()
        for item in session.scalars(
            select(ShipmentBoxItem).join(ShipmentBox).where(ShipmentBox.shipment_id == "list-0000")
        ):
            session.add(
                ShipmentReceiptItem(shipment_id="list-0000", box_item_id=item.item_id, quantity=0)
            )
    reader = service(test_database_engine)
    expected = reader.list_shipments(factory_id=FACTORY_IDS[0])
    actual = []
    for page in [1, 2, 3, 4]:
        calls = []

        def count(*args, calls=calls):
            calls.append(args[2])

        event.listen(test_database_engine, "before_cursor_execute", count)
        try:
            rows, total = reader.page_factory_shipments(factory_id=FACTORY_IDS[0], page=page)
        finally:
            event.remove(test_database_engine, "before_cursor_execute", count)
        assert total == 43
        assert len(calls) <= 2
        actual.extend(rows)
    assert [row["shipment_id"] for row in actual] == [item.shipment_id for item in expected]
    for row, item in zip(actual, expected, strict=True):
        assert row["total_quantity"] == item.total_quantity
        assert row["total_boxes"] == item.total_boxes
        assert row["status"] == item.status
        assert row["product_summary"] == "、".join(
            dict.fromkeys(line.product_name for line in item.lines)
        )
        assert row["order_summary"] == "、".join(
            dict.fromkeys(line.order_no for line in item.lines)
        )
        assert not {"boxes", "files", "lines"}.intersection(row)
    assert (
        reader.page_factory_shipments(factory_id=FACTORY_IDS[0], keyword="接口测试产品", page=3)[1]
        == 43
    )
    assert reader.page_factory_shipments(factory_id=FACTORY_IDS[0], keyword="s07-order-a")[1] == 43
    assert reader.page_factory_shipments(factory_id=FACTORY_IDS[0], keyword="%")[1] == 0
    rows, total = reader.page_factory_shipments(
        factory_id=FACTORY_IDS[0], ship_date_from=date(2026, 9, 3), ship_date_to=date(2026, 9, 3)
    )
    assert total == 14
    assert all(row["business_date"] == date(2026, 9, 3) for row in rows)
    assert reader.page_factory_shipments(factory_id=FACTORY_IDS[1])[1] == 1


def test_factory_page_api_uses_session_factory_and_validates_pagination(
    test_database_engine: Engine,
    test_database_url: str,
) -> None:
    seed_shipments(test_database_engine, 23)
    identity = IdentityAccessService(
        sessionmaker(test_database_engine, expire_on_commit=False),
        token_secret=b"test-token",
        phone_encryption_secret=b"test-phone",
        phone_digest_secret=b"test-digest",
    )
    # Same factory identity mechanism as all existing shipment endpoints.
    session = identity.issue_session(user_id=USER_IDS[0], terminal="mini")
    client = TestClient(create_app(database_url=test_database_url, identity_service=identity))
    headers = {"Authorization": f"Bearer {session.access_token}"}
    result = client.get("/api/v1/factory/shipment-page?page=2&pageSize=20", headers=headers)
    assert result.status_code == 200, result.text
    assert result.json()["total"] == 23
    assert len(result.json()["items"]) == 3
    assert client.get("/api/v1/factory/shipment-page?page=0", headers=headers).status_code == 422
    assert (
        client.get("/api/v1/factory/shipment-page?pageSize=101", headers=headers).status_code == 422
    )
    assert client.get("/api/v1/factory/shipment-page").status_code == 401
