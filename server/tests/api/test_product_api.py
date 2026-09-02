import base64
from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, text
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.private_files import FakePrivateFileStore
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
            i_id="ITEM-00" if index == 1 else f"ITEM-{index:02d}",
            sku_id=f"SKU-{index:02d}",
            name="童帽产品 00" if index == 1 else f"童帽产品 {index:02d}",
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
    with sessions() as session, session.begin():
        cached_product = session.query(Product).filter_by(source_i_id="ITEM-00").one()
        cached_product.image_cache_status = "cached"
        cached_product.image_object_key = "products/ITEM-00/cached-image.jpg"
        failed_product = session.query(Product).filter_by(source_i_id="ITEM-02").one()
        failed_product.image_cache_status = "failed"
        failed_product.image_object_key = "products/ITEM-02/old-image.jpg"
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
    image_bytes = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )
    private_files = FakePrivateFileStore(bucket="product-api-test")
    private_files.put(
        object_key="products/ITEM-00/cached-image.jpg",
        content=image_bytes,
        content_type="image/png",
    )
    app = create_app(
        database_url=test_database_url,
        identity_service=identity,
        product_service=ProductCatalogService(sessions),
        private_file_store=private_files,
    )
    image_url = (
        f"/api/v1/admin/products/{cached_product.product_id}/image"
        "?v=c2aabbcad6c04279"
    )

    with TestClient(app, base_url="https://testserver") as anonymous:
        assert anonymous.get("/api/v1/admin/products").status_code == 401
        assert anonymous.get(image_url).status_code == 401
    with TestClient(app, base_url="https://testserver") as factory_client:
        factory_client.cookies.set("ot_web_session", factory_session.access_token)
        assert factory_client.get("/api/v1/admin/products").status_code == 403
        assert factory_client.get(image_url).status_code == 403
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
        assert page.json()["items"][0]["imageUrl"] == page.json()["items"][1]["imageUrl"]
        assert page.json()["items"][0]["imageUrl"] == image_url
        failed_image = admin_client.get(
            "/api/v1/admin/products",
            params={"keyword": "SKU-02"},
        )
        assert failed_image.json()["items"][0]["imageAvailable"] is False
        assert failed_image.json()["items"][0]["imageUrl"] is None
        image = admin_client.get(image_url)
        assert image.status_code == 200
        assert image.content == image_bytes
        assert image.headers["content-type"] == "image/png"
        assert image.headers["cache-control"] == "private, max-age=31536000, immutable"
        assert image.headers["vary"] == "Cookie"
        assert admin_client.get(
            f"/api/v1/admin/products/{cached_product.product_id}/image?v=stale-version"
        ).status_code == 404
        with sessions() as session, session.begin():
            replaced_product = session.get(Product, cached_product.product_id)
            assert replaced_product is not None
            replaced_product.image_object_key = "products/ITEM-00/replaced-image.jpg"
        private_files.put(
            object_key="products/ITEM-00/replaced-image.jpg",
            content=image_bytes,
            content_type="image/png",
        )
        replaced_page = admin_client.get(
            "/api/v1/admin/products",
            params={"keyword": "SKU-00"},
        )
        replaced_image_url = replaced_page.json()["items"][0]["imageUrl"]
        assert replaced_image_url == (
            f"/api/v1/admin/products/{cached_product.product_id}/image"
            "?v=d165fa9cf567289d"
        )
        assert replaced_image_url != image_url
        assert admin_client.get(image_url).status_code == 404
        assert admin_client.get(replaced_image_url).status_code == 200
        private_files.delete(object_key="products/ITEM-00/replaced-image.jpg")
        assert admin_client.get(replaced_image_url).status_code == 404
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
            "imageUrl": None,
        }
