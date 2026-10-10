from datetime import date, datetime

from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

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
    ShipmentReturnEvent,
    ShipmentReturnLine,
)
from app.main import create_app
from app.modules.identity_access import IdentityAccessService
from tests.api.test_shipment_api import ADMIN_ID, FACTORY_IDS, ORDER_ID, USER_IDS, VARIANT_ID
from tests.api.test_shipment_summary import seed_shipments, service


def test_related_summary_respects_receipt_remapping_and_keeps_whole_shipment_quantity(
    test_database_engine: Engine, test_database_url: str,
) -> None:
    seed_shipments(test_database_engine, 8)
    with Session(test_database_engine) as session, session.begin():
        session.add(Order(order_id="other", order_no="OTHER", source="manual", tracker="松子",
                          lifecycle="PUBLISHED", created_by=ADMIN_ID, updated_by=ADMIN_ID))
        session.flush()
        line = OrderLine(order_id="other", product_variant_id=VARIANT_ID, order_quantity=100,
                         sku_id_snapshot="SKU", product_name_snapshot="测试",
                         properties_value_snapshot="蓝")
        session.add(line)
        session.flush()
        target = OrderAssignment(order_line_id=line.order_line_id, factory_id=FACTORY_IDS[0],
                                 assigned_quantity=100, factory_name_snapshot="测试")
        session.add(target)
        session.flush()
        for index in [0, 1, 2]:
            shipment_id = f"list-{index:04}"
            session.add(ShipmentReceipt(
                shipment_id=shipment_id, status="CONFIRMED" if index != 2 else "DRAFT",
                saved_by=ADMIN_ID, saved_at=datetime(2026, 10, 9), version=1,
            ))
            session.flush()
            items = session.scalars(select(ShipmentBoxItem).join(ShipmentBox).where(
                ShipmentBox.shipment_id == shipment_id,
            ).order_by(ShipmentBox.box_no)).all()
            for number, item in enumerate(items):
                session.add(ShipmentReceiptItem(
                    shipment_id=shipment_id, box_item_id=item.item_id,
                    order_assignment_id=target.order_assignment_id,
                    quantity=(0 if number == 0 else 7) if index == 0 else 0,
                ))
        box = session.scalar(select(ShipmentBox).where(ShipmentBox.shipment_id == "list-0003"))
        assert box
        session.add(ShipmentBoxItem(
            box_id=box.box_id, order_assignment_id=target.order_assignment_id, quantity=11,
        ))
        session.add(ShipmentLine(
            shipment_id="list-0003", order_assignment_id=target.order_assignment_id,
            quantity=11, order_no_snapshot="OTHER", sku_id_snapshot="SKU",
            product_name_snapshot="测试", properties_value_snapshot="蓝",
        ))
        original_line = session.scalar(select(ShipmentLine).where(
            ShipmentLine.shipment_id == "list-0003",
        ))
        assert original_line
        returned = ShipmentReturnEvent(
            event_id="related-return", shipment_id="list-0003", reason="测试退回",
            returned_by=ADMIN_ID, return_date=date(2026, 10, 9),
            created_at=datetime(2026, 10, 9), idempotency_key="related-return",
        )
        session.add(returned)
        session.flush()
        session.add(ShipmentReturnLine(
            event_id=returned.event_id, shipment_line_id=original_line.line_id,
            quantity=2, before_shipped_quantity=9, after_shipped_quantity=7,
        ))
        for index, change in [(4, {"status": "DRAFT"}), (5, {"deleted_at": datetime(2026, 10, 9)}),
                              (6, {"source_shipment_id": "list-0000"})]:
            shipment = session.get(Shipment, f"list-{index:04}")
            assert shipment
            for key, value in change.items():
                setattr(shipment, key, value)
    reader = service(test_database_engine)
    for order_id, expected in [(ORDER_ID, [("list-0007", 17), ("list-0003", 20), ("list-0002", 7)]),
                               ("other", [("list-0003", 20), ("list-0000", 7)]), ("missing", [])]:
        previous = reader.list_shipments(order_id=order_id)
        assert [(row.shipment_id, row.total_quantity) for row in previous] == expected

    identity = IdentityAccessService(
        sessionmaker(test_database_engine, expire_on_commit=False),
        token_secret=b"related-token", phone_encryption_secret=b"related-phone",
        phone_digest_secret=b"related-digest",
    )
    admin = identity.issue_session(user_id=ADMIN_ID, terminal="web")
    factory = identity.issue_session(user_id=USER_IDS[0], terminal="mini")
    app = create_app(database_url=test_database_url, identity_service=identity)
    url = f"/api/v1/admin/shipments?orderId={ORDER_ID}"
    with TestClient(app, base_url="https://testserver") as client:
        assert client.get(url).status_code == 401
        denied = client.get(url, headers={"Authorization": f"Bearer {factory.access_token}"})
        assert denied.status_code == 403
        client.cookies.set("ot_web_session", admin.access_token)
        response = client.get(url)
        assert response.status_code == 200
        assert response.json()["total"] == 3
        item = response.json()["items"][1]
        assert {key: item[key] for key in (
            "shipmentId", "shipmentNo", "businessDate", "totalQuantity",
        )} == {
            "shipmentId": "list-0003", "shipmentNo": "发货3",
            "businessDate": date(2026, 9, 1).isoformat(), "totalQuantity": 20,
        }
