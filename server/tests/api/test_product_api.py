from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, text
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.product import FakeJstProductSource, SourceProductVariant
from app.db.models import Product, ProductSyncRun, ProductVariant, User
from app.main import create_app
from app.modules.identity_access import FeishuProfile, IdentityAccessService
from app.modules.product_sync import ProductCatalogService, ProductSyncService


def test_admin_product_list_enforces_role_and_returns_only_available_searchable_page(
    test_database_engine: Engine,
    test_database_url: str,
) -> None:
    sessions = sessionmaker(test_database_engine, class_=Session, expire_on_commit=False)
    with test_database_engine.begin() as connection:
        connection.execute(text("UPDATE users SET mini_avatar_file_id = NULL"))
        connection.execute(text("DELETE FROM stored_files"))
        connection.execute(text("DELETE FROM mini_login_attempts"))
        connection.execute(text("UPDATE factory_applications SET previous_application_id = NULL"))
        connection.execute(text("DELETE FROM factory_applications"))
        connection.execute(text("UPDATE admin_applications SET previous_application_id = NULL"))
        connection.execute(text("DELETE FROM admin_applications"))
        connection.execute(text("DELETE FROM sms_challenges"))
        connection.execute(text("DELETE FROM user_sessions"))
        connection.execute(text("DELETE FROM oauth_states"))
        connection.execute(text("DELETE FROM external_identities"))
        connection.execute(text("DELETE FROM audit_logs"))
    with sessions() as session, session.begin():
        session.execute(delete(ProductVariant))
        session.execute(delete(ProductSyncRun))
        session.execute(delete(Product))
        session.execute(delete(User))
    records = [
        SourceProductVariant(
            i_id=f"ITEM-{index:02d}",
            sku_id=f"SKU-{index:02d}",
            name=f"童帽产品 {index:02d}",
            properties_value=f"蓝色,{50 + index}",
            pic=None,
            category="童帽春夏",
            enabled=1,
            source_modified_at=datetime(2026, 8, 21, 9, index),
        )
        for index in range(12)
    ]
    ProductSyncService(
        sessions,
        source=FakeJstProductSource(
            initial_pages=[records],
            candidate_cursor="cursor-api",
        ),
    ).run_initial(request_id="request-api", worker_id="worker-test")
    identity = IdentityAccessService(
        sessions,
        token_secret=b"test-token-secret-not-for-production",
        phone_encryption_secret=b"test-phone-encryption-secret",
        phone_digest_secret=b"test-phone-digest-secret",
    )
    admin = identity.bootstrap_super_admin(
        scope="tenant-a/app-a",
        profile=FeishuProfile(subject="ou_product_admin", display_name="松子"),
        operator_source="test",
        request_id="request-bootstrap-product-admin",
    )
    admin_session = identity.issue_session(user_id=admin.user_id, terminal="web")
    with sessions() as session, session.begin():
        factory_user = User(
            user_id="factory-product-reader",
            role="factory",
            is_enabled=True,
            feishu_display_name="工厂用户",
        )
        session.add(factory_user)
    factory_session = identity.issue_session(
        user_id="factory-product-reader",
        terminal="web",
    )
    app = create_app(
        database_url=test_database_url,
        identity_service=identity,
        product_service=ProductCatalogService(sessions),
    )

    with TestClient(app, base_url="https://testserver") as anonymous:
        assert anonymous.get("/api/v1/admin/products").status_code == 401
    with TestClient(app, base_url="https://testserver") as factory_client:
        factory_client.cookies.set("ot_web_session", factory_session.access_token)
        assert factory_client.get("/api/v1/admin/products").status_code == 403
    with TestClient(app, base_url="https://testserver") as admin_client:
        admin_client.cookies.set("ot_web_session", admin_session.access_token)
        page = admin_client.get(
            "/api/v1/admin/products",
            params={"page": 2, "pageSize": 10, "sortBy": "skuId", "sortOrder": "desc"},
        )
        assert page.status_code == 200
        assert page.json()["total"] == 12
        assert page.json()["page"] == 2
        assert [item["skuId"] for item in page.json()["items"]] == ["SKU-01", "SKU-00"]
        searched = admin_client.get(
            "/api/v1/admin/products",
            params={"keyword": "蓝色,55"},
        )
        assert searched.status_code == 200
        assert searched.json()["total"] == 1
        assert searched.json()["items"][0] == {
            "variantId": searched.json()["items"][0]["variantId"],
            "iId": "ITEM-05",
            "skuId": "SKU-05",
            "name": "童帽产品 05",
            "propertiesValue": "蓝色,55",
            "imageAvailable": False,
        }
