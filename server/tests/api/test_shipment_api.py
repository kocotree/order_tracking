from datetime import date, datetime

from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import (
    AuditLog,
    Factory,
    IdempotencyRecord,
    Order,
    OrderAssignment,
    OrderLine,
    OutboxMessage,
    Product,
    ProductVariant,
    QuantityLedger,
    Shipment,
    ShipmentBox,
    ShipmentBoxItem,
    ShipmentLine,
    ShipmentNumberCounter,
    User,
    UserSession,
)
from app.main import create_app
from app.modules.identity_access import IdentityAccessService

USER_IDS = ["shipment-api-factory-a-user", "shipment-api-factory-b-user"]
FACTORY_IDS = ["shipment-api-factory-a", "shipment-api-factory-b"]
ORDER_ID = "shipment-api-order-a"
PRODUCT_ID = "shipment-api-product"
VARIANT_ID = "shipment-api-variant"


def _clean(engine: Engine) -> None:
    with Session(engine) as session, session.begin():
        shipment_ids = select(Shipment.shipment_id).where(Shipment.factory_id.in_(FACTORY_IDS))
        box_ids = select(ShipmentBox.box_id).where(ShipmentBox.shipment_id.in_(shipment_ids))
        assignment_ids = select(OrderAssignment.order_assignment_id).where(
            OrderAssignment.factory_id.in_(FACTORY_IDS)
        )
        session.execute(delete(QuantityLedger).where(QuantityLedger.source_id.in_(shipment_ids)))
        session.execute(delete(ShipmentLine).where(ShipmentLine.shipment_id.in_(shipment_ids)))
        session.execute(delete(ShipmentBoxItem).where(ShipmentBoxItem.box_id.in_(box_ids)))
        session.execute(delete(ShipmentBox).where(ShipmentBox.shipment_id.in_(shipment_ids)))
        session.execute(delete(OutboxMessage).where(OutboxMessage.aggregate_id.in_(shipment_ids)))
        session.execute(delete(AuditLog).where(AuditLog.target_id == ORDER_ID))
        session.execute(
            delete(IdempotencyRecord).where(
                IdempotencyRecord.scope.in_([f"shipment.submit:{user_id}" for user_id in USER_IDS])
            )
        )
        session.execute(delete(Shipment).where(Shipment.factory_id.in_(FACTORY_IDS)))
        session.execute(
            delete(QuantityLedger).where(QuantityLedger.order_assignment_id.in_(assignment_ids))
        )
        session.execute(delete(OrderAssignment).where(OrderAssignment.factory_id.in_(FACTORY_IDS)))
        session.execute(delete(OrderLine).where(OrderLine.order_id == ORDER_ID))
        session.execute(delete(Order).where(Order.order_id == ORDER_ID))
        session.execute(delete(UserSession).where(UserSession.user_id.in_(USER_IDS)))
        session.execute(delete(ProductVariant).where(ProductVariant.variant_id == VARIANT_ID))
        session.execute(delete(Product).where(Product.product_id == PRODUCT_ID))
        session.execute(delete(User).where(User.user_id.in_(USER_IDS)))
        session.execute(delete(Factory).where(Factory.factory_id.in_(FACTORY_IDS)))
        session.execute(
            delete(ShipmentNumberCounter).where(
                ShipmentNumberCounter.business_date == date(2026, 8, 25)
            )
        )


def _seed(engine: Engine, *, initial_shipped_quantity: int = 0) -> int:
    now = datetime(2026, 8, 25, 8, 0)
    with Session(engine) as session, session.begin():
        session.add_all(
            [
                Factory(
                    factory_id=factory_id,
                    supplier_number=f"S07-{index}",
                    factory_name=f"S07接口工厂{index}",
                    factory_code=f"S07-{index}",
                    is_enabled=True,
                )
                for index, factory_id in enumerate(FACTORY_IDS, 1)
            ]
        )
        session.flush()
        session.add_all(
            [
                User(
                    user_id=user_id,
                    role="factory",
                    is_enabled=True,
                    feishu_display_name=f"S07工厂用户{index}",
                    factory_id=factory_id,
                    factory_position="employee",
                )
                for index, (user_id, factory_id) in enumerate(
                    zip(USER_IDS, FACTORY_IDS, strict=True), 1
                )
            ]
        )
        session.add(
            Product(
                product_id=PRODUCT_ID,
                source_i_id="ITEM-SHIPMENT-API",
                name="S07接口测试产品",
                is_available=True,
                source_modified_at=now,
                first_synced_at=now,
                last_synced_at=now,
            )
        )
        session.add(
            ProductVariant(
                variant_id=VARIANT_ID,
                product_id=PRODUCT_ID,
                source_sku_id="SKU-SHIPMENT-API",
                properties_value="海军蓝 / 120",
                source_category="童帽春夏",
                source_enabled=1,
                is_available=True,
                source_modified_at=now,
                first_synced_at=now,
                last_synced_at=now,
            )
        )
        session.flush()
        session.add(
            Order(
                order_id=ORDER_ID,
                order_no="S07-ORDER-A",
                source="manual",
                order_date=date(2026, 8, 25),
                tracker="松子",
                contract_ship_date=date(2026, 9, 1),
                lifecycle="PUBLISHED",
                version=1,
                published_at=now,
                published_by=USER_IDS[0],
                created_by=USER_IDS[0],
                updated_by=USER_IDS[0],
                created_at=now,
                updated_at=now,
            )
        )
        session.flush()
        line = OrderLine(
            order_id=ORDER_ID,
            product_variant_id=VARIANT_ID,
            order_quantity=40,
            sku_id_snapshot="SKU-SHIPMENT-API",
            product_name_snapshot="S07接口测试产品",
            properties_value_snapshot="海军蓝 / 120",
            category_snapshot="童帽春夏",
            created_at=now,
            updated_at=now,
        )
        session.add(line)
        session.flush()
        assignment = OrderAssignment(
            order_line_id=line.order_line_id,
            factory_id=FACTORY_IDS[0],
            assigned_quantity=40,
            initial_shipped_quantity=initial_shipped_quantity,
            factory_name_snapshot="S07接口工厂1",
            created_at=now,
            updated_at=now,
        )
        session.add(assignment)
        session.flush()
        return assignment.order_assignment_id


def test_factory_creates_one_server_draft_scoped_to_its_factory(
    test_database_engine: Engine,
    test_database_url: str,
) -> None:
    _clean(test_database_engine)
    _seed(test_database_engine)
    sessions = sessionmaker(test_database_engine, class_=Session, expire_on_commit=False)
    identity = IdentityAccessService(
        sessions,
        token_secret=b"shipment-api-token-secret",
        phone_encryption_secret=b"shipment-api-phone-encryption",
        phone_digest_secret=b"shipment-api-phone-digest",
    )
    factory_a = identity.issue_session(user_id=USER_IDS[0], terminal="mini")
    factory_b = identity.issue_session(user_id=USER_IDS[1], terminal="mini")
    app = create_app(database_url=test_database_url, identity_service=identity)

    try:
        with TestClient(app, base_url="https://testserver") as client:
            client.headers["Authorization"] = f"Bearer {factory_a.access_token}"
            created = client.post(
                "/api/v1/factory/shipments/drafts",
                json={"preferredOrderId": ORDER_ID},
            )
            assert created.status_code == 201
            assert {
                key: created.json()[key]
                for key in (
                    "shipmentId",
                    "status",
                    "factoryId",
                    "factoryName",
                    "createdBy",
                    "preferredOrderId",
                )
            } == {
                "shipmentId": created.json()["shipmentId"],
                "status": "DRAFT",
                "factoryId": FACTORY_IDS[0],
                "factoryName": "",
                "createdBy": USER_IDS[0],
                "preferredOrderId": ORDER_ID,
            }

            repeated = client.post(
                "/api/v1/factory/shipments/drafts",
                json={"preferredOrderId": ORDER_ID},
            )
            assert repeated.status_code == 200
            assert repeated.json()["shipmentId"] == created.json()["shipmentId"]

            with TestClient(app, base_url="https://testserver") as other_factory:
                other_factory.headers["Authorization"] = f"Bearer {factory_b.access_token}"
                other_created = other_factory.post(
                    "/api/v1/factory/shipments/drafts",
                    json={},
                )
                assert other_created.status_code == 201
                assert other_created.json()["factoryId"] == FACTORY_IDS[1]
                assert other_created.json()["shipmentId"] != created.json()["shipmentId"]
    finally:
        _clean(test_database_engine)


def test_factory_saves_and_submits_boxes_then_all_terminals_query_same_shipment(
    test_database_engine: Engine,
    test_database_url: str,
) -> None:
    _clean(test_database_engine)
    assignment_id = _seed(test_database_engine, initial_shipped_quantity=5)
    sessions = sessionmaker(test_database_engine, class_=Session, expire_on_commit=False)
    identity = IdentityAccessService(
        sessions,
        token_secret=b"shipment-submit-token-secret",
        phone_encryption_secret=b"shipment-submit-phone-encryption",
        phone_digest_secret=b"shipment-submit-phone-digest",
    )
    factory_a = identity.issue_session(user_id=USER_IDS[0], terminal="mini")
    factory_b = identity.issue_session(user_id=USER_IDS[1], terminal="mini")
    app = create_app(database_url=test_database_url, identity_service=identity)

    try:
        with TestClient(app, base_url="https://testserver") as client:
            client.headers["Authorization"] = f"Bearer {factory_a.access_token}"
            shipment_id = client.post(
                "/api/v1/factory/shipments/drafts",
                json={"preferredOrderId": ORDER_ID},
            ).json()["shipmentId"]
            saved = client.put(
                f"/api/v1/factory/shipments/drafts/{shipment_id}",
                json={
                    "boxes": [
                        {
                            "boxNo": box_no,
                            "groupKey": "group-a" if box_no < 3 else None,
                            "items": [{"assignmentId": assignment_id, "quantity": quantity}],
                        }
                        for box_no, quantity in ((1, 10), (2, 10), (3, 3))
                    ],
                    "note": "尾箱混装",
                },
            )
            assert saved.status_code == 200
            assert saved.json()["totalBoxes"] == 3
            assert saved.json()["totalQuantity"] == 23

            submitted = client.post(
                f"/api/v1/factory/shipments/drafts/{shipment_id}/submit",
                headers={"Idempotency-Key": "shipment-submit-same-key"},
            )
            assert submitted.status_code == 200
            assert submitted.json()["status"] == "SHIPPED"
            assert submitted.json()["shipmentNo"].startswith("FH")
            assert submitted.json()["factoryName"] == "S07接口工厂1"
            assert submitted.json()["lines"][0]["quantity"] == 23

            repeated = client.post(
                f"/api/v1/factory/shipments/drafts/{shipment_id}/submit",
                headers={"Idempotency-Key": "shipment-submit-same-key"},
            )
            assert repeated.json()["shipmentNo"] == submitted.json()["shipmentNo"]

            listing = client.get("/api/v1/factory/shipments")
            assert listing.status_code == 200
            assert listing.json()["total"] == 1
            assert listing.json()["items"][0]["shipmentId"] == shipment_id
            detail = client.get(f"/api/v1/factory/shipments/{shipment_id}")
            assert detail.json()["boxes"][2]["items"][0]["quantity"] == 3
            catalog = client.get("/api/v1/factory/shipment-catalog").json()["items"][0]
            assert catalog["shippedQuantity"] == 28
            assert catalog["pendingQuantity"] == 12
            order = client.get(f"/api/v1/orders/{ORDER_ID}").json()
            assert order["shippedQuantity"] == 28

        with TestClient(app, base_url="https://testserver") as other_factory:
            other_factory.headers["Authorization"] = f"Bearer {factory_b.access_token}"
            assert other_factory.get(f"/api/v1/factory/shipments/{shipment_id}").status_code == 404
    finally:
        _clean(test_database_engine)


def test_factory_catalog_returns_only_its_published_assignments_with_initial_progress(
    test_database_engine: Engine,
    test_database_url: str,
) -> None:
    _clean(test_database_engine)
    assignment_id = _seed(test_database_engine, initial_shipped_quantity=5)
    sessions = sessionmaker(test_database_engine, class_=Session, expire_on_commit=False)
    identity = IdentityAccessService(
        sessions,
        token_secret=b"shipment-catalog-token-secret",
        phone_encryption_secret=b"shipment-catalog-phone-encryption",
        phone_digest_secret=b"shipment-catalog-phone-digest",
    )
    factory_a = identity.issue_session(user_id=USER_IDS[0], terminal="mini")
    factory_b = identity.issue_session(user_id=USER_IDS[1], terminal="mini")
    app = create_app(database_url=test_database_url, identity_service=identity)

    try:
        with TestClient(app, base_url="https://testserver") as client:
            client.headers["Authorization"] = f"Bearer {factory_a.access_token}"
            response = client.get("/api/v1/factory/shipment-catalog")
            assert response.status_code == 200
            assert response.json() == {
                "items": [
                    {
                        "assignmentId": assignment_id,
                        "orderId": ORDER_ID,
                        "orderNo": "S07-ORDER-A",
                        "contractShipDate": "2026-09-01",
                        "productName": "S07接口测试产品",
                        "propertiesValue": "海军蓝 / 120",
                        "assignedQuantity": 40,
                        "shippedQuantity": 5,
                        "pendingQuantity": 35,
                    }
                ],
                "total": 1,
            }

            with TestClient(app, base_url="https://testserver") as other_factory:
                other_factory.headers["Authorization"] = f"Bearer {factory_b.access_token}"
                assert other_factory.get("/api/v1/factory/shipment-catalog").json() == {
                    "items": [],
                    "total": 0,
                }
    finally:
        _clean(test_database_engine)
