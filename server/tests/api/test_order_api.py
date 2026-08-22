from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import (
    AuditLog,
    Factory,
    IdempotencyRecord,
    Order,
    OrderAssignment,
    OrderCompletionRecord,
    OrderLine,
    OutboxMessage,
    Product,
    ProductVariant,
    User,
    UserSession,
)
from app.main import create_app
from app.modules.identity_access import IdentityAccessService
from app.modules.orders import OrderService

USER_IDS = ["order-api-admin", "order-api-a", "order-api-b", "order-api-c"]
FACTORY_IDS = ["order-api-factory-a", "order-api-factory-b", "order-api-factory-c"]


def _clean(engine: Engine) -> None:
    with Session(engine) as session, session.begin():
        session.execute(delete(OrderCompletionRecord))
        session.execute(delete(OrderAssignment))
        session.execute(delete(OrderLine))
        session.execute(delete(Order))
        session.execute(delete(OutboxMessage).where(OutboxMessage.aggregate_type == "order"))
        session.execute(delete(AuditLog).where(AuditLog.target_type == "order"))
        session.execute(
            delete(IdempotencyRecord).where(IdempotencyRecord.scope.like("order.%"))
        )
        session.execute(delete(UserSession).where(UserSession.user_id.in_(USER_IDS)))
        session.execute(
            delete(ProductVariant).where(ProductVariant.variant_id == "order-api-variant")
        )
        session.execute(delete(Product).where(Product.product_id == "order-api-product"))
        session.execute(delete(User).where(User.user_id.in_(USER_IDS)))
        session.execute(delete(Factory).where(Factory.factory_id.in_(FACTORY_IDS)))


def _seed(engine: Engine) -> None:
    with Session(engine) as session, session.begin():
        session.add_all(
            [
                Factory(
                    factory_id=factory_id,
                    supplier_number=f"S04-{index}",
                    factory_name=f"接口工厂{index}",
                    factory_code=f"S04-{index}",
                    is_enabled=True,
                )
                for index, factory_id in enumerate(FACTORY_IDS, 1)
            ]
        )
        session.flush()
        session.add_all(
            [
                User(
                    user_id="order-api-admin",
                    role="admin",
                    is_enabled=True,
                    feishu_display_name="松子",
                ),
                *[
                    User(
                        user_id=user_id,
                        role="factory",
                        is_enabled=True,
                        feishu_display_name=f"工厂用户{index}",
                        factory_id=factory_id,
                        factory_position="employee",
                    )
                    for index, (user_id, factory_id) in enumerate(
                        zip(USER_IDS[1:], FACTORY_IDS, strict=True), 1
                    )
                ],
            ]
        )
        session.add(
            Product(
                product_id="order-api-product",
                source_i_id="ITEM-ORDER-API",
                name="接口测试产品",
                is_available=True,
                source_modified_at=datetime(2026, 8, 21, 8, 0),
                first_synced_at=datetime(2026, 8, 21, 8, 0),
                last_synced_at=datetime(2026, 8, 21, 8, 0),
            )
        )
        session.add(
            ProductVariant(
                variant_id="order-api-variant",
                product_id="order-api-product",
                source_sku_id="SKU-ORDER-API",
                properties_value="蓝色 / 120",
                source_category="童帽春夏",
                source_enabled=1,
                is_available=True,
                source_modified_at=datetime(2026, 8, 21, 8, 0),
                first_synced_at=datetime(2026, 8, 21, 8, 0),
                last_synced_at=datetime(2026, 8, 21, 8, 0),
            )
        )


def test_order_api_enforces_terminal_and_factory_visibility(
    test_database_engine: Engine,
    test_database_url: str,
) -> None:
    _clean(test_database_engine)
    _seed(test_database_engine)
    sessions = sessionmaker(
        test_database_engine, class_=Session, expire_on_commit=False
    )
    identity = IdentityAccessService(
        sessions,
        token_secret=b"order-api-token-secret",
        phone_encryption_secret=b"order-api-phone-encryption",
        phone_digest_secret=b"order-api-phone-digest",
    )
    admin_web = identity.issue_session(user_id=USER_IDS[0], terminal="web")
    admin_mini = identity.issue_session(user_id=USER_IDS[0], terminal="mini")
    factory_a = identity.issue_session(user_id=USER_IDS[1], terminal="mini")
    factory_c = identity.issue_session(user_id=USER_IDS[3], terminal="mini")
    app = create_app(
        database_url=test_database_url,
        identity_service=identity,
        order_service=OrderService(sessions),
    )
    draft_payload = {
        "orderNo": " api-81 ",
        "orderDate": "2026-08-21",
        "tracker": "松子",
        "contractShipDate": "2026-08-30",
        "lines": [
            {
                "variantId": "order-api-variant",
                "orderQuantity": 100,
                "assignments": [
                    {"factoryId": FACTORY_IDS[0], "quantity": 40},
                    {"factoryId": FACTORY_IDS[1], "quantity": 60},
                ],
            }
        ],
    }
    try:
        with TestClient(app, base_url="https://testserver") as client:
            assert client.get("/api/v1/orders").status_code == 401
            client.cookies.set("ot_web_session", admin_web.access_token)
            client.cookies.set("ot_csrf", admin_web.csrf_token or "")
            created = client.post(
                "/api/v1/admin/orders",
                json=draft_payload,
                headers={"X-CSRF-Token": admin_web.csrf_token or ""},
            )
            assert created.status_code == 201
            assert created.json()["orderNo"] == "API-81"
            order_id = created.json()["orderId"]

            with TestClient(app, base_url="https://testserver") as mini_admin:
                mini_admin.headers["Authorization"] = f"Bearer {admin_mini.access_token}"
                assert mini_admin.get("/api/v1/orders").json()["total"] == 0
                assert mini_admin.get(f"/api/v1/orders/{order_id}").status_code == 404

            published = client.post(
                f"/api/v1/admin/orders/{order_id}/publish",
                json={"version": created.json()["version"]},
                headers={
                    "X-CSRF-Token": admin_web.csrf_token or "",
                    "Idempotency-Key": "order-api-publish",
                },
            )
            assert published.status_code == 200

            second_payload = {
                **draft_payload,
                "orderNo": "API-90",
                "lines": [
                    {
                        "variantId": "order-api-variant",
                        "orderQuantity": 30,
                        "assignments": [
                            {"factoryId": FACTORY_IDS[1], "quantity": 30}
                        ],
                    }
                ],
            }
            second_created = client.post(
                "/api/v1/admin/orders",
                json=second_payload,
                headers={"X-CSRF-Token": admin_web.csrf_token or ""},
            )
            assert second_created.status_code == 201
            second_published = client.post(
                f"/api/v1/admin/orders/{second_created.json()['orderId']}/publish",
                json={"version": second_created.json()["version"]},
                headers={
                    "X-CSRF-Token": admin_web.csrf_token or "",
                    "Idempotency-Key": "order-api-publish-second",
                },
            )
            assert second_published.status_code == 200

            assert client.get("/api/v1/orders?category=帽子").json()["total"] == 2
            assert client.get("/api/v1/orders?category=服装").json()["total"] == 0
            multi_factory = client.get(
                "/api/v1/orders",
                params=[
                    ("factoryIds", FACTORY_IDS[0]),
                    ("factoryIds", FACTORY_IDS[2]),
                ],
            ).json()
            assert multi_factory["total"] == 1
            sorted_orders = client.get(
                "/api/v1/orders?sortBy=orderNoDesc"
            ).json()
            assert [item["orderNo"] for item in sorted_orders["items"]] == [
                "API-90",
                "API-81",
            ]

            with TestClient(app, base_url="https://testserver") as factory_client:
                factory_client.headers["Authorization"] = f"Bearer {factory_a.access_token}"
                listed = factory_client.get("/api/v1/orders").json()
                assert listed["total"] == 1
                assert listed["items"][0]["totalQuantity"] == 40
                assert [
                    item["factoryId"] for item in listed["items"][0]["factoryProgress"]
                ] == [FACTORY_IDS[0]]

            with TestClient(app, base_url="https://testserver") as other_factory:
                other_factory.headers["Authorization"] = f"Bearer {factory_c.access_token}"
                assert other_factory.get(f"/api/v1/orders/{order_id}").status_code == 404
                assert (
                    other_factory.post(
                        f"/api/v1/admin/orders/{order_id}/complete",
                        headers={"Idempotency-Key": "forbidden-mini-complete"},
                    ).status_code
                    == 401
                )
    finally:
        _clean(test_database_engine)
