from datetime import date, datetime

from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import (
    Factory,
    Order,
    OrderAssignment,
    OrderLine,
    Product,
    ProductVariant,
    Shipment,
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
        session.execute(delete(Shipment).where(Shipment.factory_id.in_(FACTORY_IDS)))
        session.execute(delete(OrderAssignment).where(OrderAssignment.factory_id.in_(FACTORY_IDS)))
        session.execute(delete(OrderLine).where(OrderLine.order_id == ORDER_ID))
        session.execute(delete(Order).where(Order.order_id == ORDER_ID))
        session.execute(delete(UserSession).where(UserSession.user_id.in_(USER_IDS)))
        session.execute(delete(ProductVariant).where(ProductVariant.variant_id == VARIANT_ID))
        session.execute(delete(Product).where(Product.product_id == PRODUCT_ID))
        session.execute(delete(User).where(User.user_id.in_(USER_IDS)))
        session.execute(delete(Factory).where(Factory.factory_id.in_(FACTORY_IDS)))


def _seed(engine: Engine) -> None:
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
        session.add(
            OrderAssignment(
                order_line_id=line.order_line_id,
                factory_id=FACTORY_IDS[0],
                assigned_quantity=40,
                initial_shipped_quantity=0,
                factory_name_snapshot="S07接口工厂1",
                created_at=now,
                updated_at=now,
            )
        )


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
            assert created.json() == {
                "shipmentId": created.json()["shipmentId"],
                "status": "DRAFT",
                "factoryId": FACTORY_IDS[0],
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
