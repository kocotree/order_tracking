import base64
import hashlib
from datetime import datetime
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.identity import FakeFeishuIdentity
from app.adapters.private_files import FakePrivateFileStore
from app.db.models import Notification, Product, ProductVariant
from app.main import create_app
from app.modules.factory_access import FactoryAccessService
from app.modules.identity_access import FeishuProfile, IdentityAccessService

RESOURCE = "http://testserver/mcp"
CLIENT_ID = "codex-issue156-test"
CALLBACK = "http://127.0.0.1:49152/callback/codexNonce156"
VERIFIER = "v" * 43
CHALLENGE = base64.urlsafe_b64encode(
    hashlib.sha256(VERIFIER.encode()).digest()
).rstrip(b"=").decode()
IMAGE = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _access(client: TestClient, code: str) -> dict[str, str]:
    started = client.get("/api/v1/auth/feishu/start", follow_redirects=False)
    state = parse_qs(urlparse(started.headers["location"]).query)["state"][0]
    completed_login = client.get(
        "/api/v1/auth/feishu/callback", params={"state": state, "code": code},
        follow_redirects=False,
    )
    assert completed_login.status_code == 303, completed_login.json()
    authorized = client.get("/oauth/authorize", params={
        "client_id": CLIENT_ID, "redirect_uri": CALLBACK, "resource": RESOURCE,
        "scope": "order_tracking.admin", "state": "issue156",
        "code_challenge": CHALLENGE, "code_challenge_method": "S256",
        "response_type": "code",
    }, follow_redirects=False)
    completed = client.get(authorized.headers["location"], follow_redirects=False)
    oauth_code = parse_qs(urlparse(completed.headers["location"]).query)["code"][0]
    issued = client.post("/oauth/token", data={
        "grant_type": "authorization_code", "client_id": CLIENT_ID,
        "redirect_uri": CALLBACK, "resource": RESOURCE,
        "code": oauth_code, "code_verifier": VERIFIER,
    })
    assert issued.status_code == 200
    return {
        "Authorization": f"Bearer {issued.json()['access_token']}",
        "Accept": "application/json, text/event-stream",
    }


def _tool(client: TestClient, headers: dict[str, str], name: str, **arguments):
    response = client.post("/mcp", headers=headers, json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    })
    assert response.status_code == 200
    return response.json()["result"]


def test_agent_directory_uses_web_rules_and_owner_scope(
    test_database_engine: Engine, test_database_url: str, monkeypatch,
) -> None:
    monkeypatch.setenv("ORDER_TRACKING_MCP_PUBLIC_URL", RESOURCE)
    monkeypatch.setenv("ORDER_TRACKING_MCP_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("ORDER_TRACKING_WEB_COOKIE_SECURE", "false")
    monkeypatch.setenv("ORDER_TRACKING_IDENTITY_TOKEN_SECRET", "issue156-token-secret")
    sessions = sessionmaker(test_database_engine, class_=Session, expire_on_commit=False)
    identity = IdentityAccessService(
        sessions,
        feishu_identity=FakeFeishuIdentity(profiles={
            "super-code": FeishuProfile(
                subject="issue156-super", display_name="最高管理员", phone="13812345611",
            ),
            "admin-code": FeishuProfile(
                subject="issue156-admin", display_name="普通管理员", phone="13812345612",
            ),
        }, scope="tenant-test/app-test"),
        super_admin_subjects={"issue156-super"},
        token_secret=b"issue156-token-secret",
        phone_encryption_secret=b"issue156-phone-secret",
        phone_digest_secret=b"issue156-digest-secret",
    )
    files = FakePrivateFileStore(bucket="issue156-files")
    files.put(object_key="products/issue156.png", content=IMAGE, content_type="image/png")
    app = create_app(database_url=test_database_url, identity_service=identity,
                     private_file_store=files)
    factories = FactoryAccessService(sessions)

    with TestClient(app) as client:
        super_headers = _access(client, "super-code")
        super_id = client.get("/api/v1/me").json()["userId"]
        listed_tools = client.post("/mcp", headers=super_headers, json={
            "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {},
        }).json()["result"]["tools"]
        assert {item["name"] for item in listed_tools} >= {
            "list_factories", "get_factory", "create_factory", "update_factory",
            "list_products", "get_product_image", "list_factory_applications",
            "get_factory_application", "approve_factory_application",
            "reject_factory_application", "list_users", "set_user_enabled",
            "list_notifications", "get_unread_count", "mark_notification_read",
        }
        created = _tool(client, super_headers, "create_factory", supplier_number="S156",
                        factory_name="测试工厂", factory_code="TEST", contacts=[])
        assert created.get("isError") is not True
        factory = created["structuredContent"]
        factory_id = factory["factoryId"]
        assert _tool(client, super_headers, "create_factory", supplier_number="S156",
                     factory_name="重复编号", factory_code="DUP")["isError"] is True
        second_factory = _tool(
            client, super_headers, "create_factory", supplier_number="S157",
            factory_name="另一工厂", factory_code="OTHER",
        )["structuredContent"]["factoryId"]
        first_page = _tool(client, super_headers, "list_factories", page=1, page_size=1)[
            "structuredContent"]
        second_page = _tool(client, super_headers, "list_factories", page=2, page_size=1)[
            "structuredContent"]
        assert first_page["total"] == second_page["total"] == 2
        assert {first_page["items"][0]["factoryId"], second_page["items"][0]["factoryId"]} == {
            factory_id, second_factory,
        }
        assert _tool(client, super_headers, "get_factory", factory_id=factory_id)[
            "structuredContent"]["supplierNumber"] == "S156"
        updated = _tool(client, super_headers, "update_factory", factory_id=factory_id,
                        version=factory["version"], factory_name="测试工厂二",
                        factory_code="TEST", contacts=[])
        assert updated["structuredContent"]["factoryName"] == "测试工厂二"
        assert _tool(client, super_headers, "update_factory", factory_id=factory_id,
                     version=factory["version"], factory_name="旧版本",
                     factory_code="TEST")["isError"] is True

        applicant = identity.resolve_feishu_identity(
            scope="tenant-test/app-test",
            profile=FeishuProfile(
                subject="issue156-applicant", display_name="申请人", phone="13812345613",
            ),
            request_id="issue156-applicant", auto_grant_admin=False,
        )
        application = factories.submit_factory_application(
            user_id=applicant.user_id, real_name="申请人", position="employee",
            factory_id=factory_id, request_id="issue156-application",
        )
        assert _tool(client, super_headers, "list_factory_applications")[
            "structuredContent"]["total"] == 1
        assert _tool(client, super_headers, "get_factory_application",
                     application_id=application.application_id)[
            "structuredContent"]["applicationId"] == application.application_id
        approved = _tool(client, super_headers, "approve_factory_application",
                         application_id=application.application_id,
                         version=application.version, factory_id=factory_id)
        assert approved["structuredContent"]["status"] == "approved"
        assert _tool(client, super_headers, "approve_factory_application",
                     application_id=application.application_id,
                     version=application.version, factory_id=factory_id)["isError"] is True
        rejected_applicant = identity.resolve_feishu_identity(
            scope="tenant-test/app-test",
            profile=FeishuProfile(
                subject="issue156-rejected", display_name="待拒绝", phone="13812345614",
            ),
            request_id="issue156-rejected", auto_grant_admin=False,
        )
        rejected_application = factories.submit_factory_application(
            user_id=rejected_applicant.user_id, real_name="待拒绝", position="owner",
            factory_id=factory_id, request_id="issue156-rejected-application",
        )
        assert _tool(client, super_headers, "reject_factory_application",
                     application_id=rejected_application.application_id,
                     version=rejected_application.version, reason="")["isError"] is True
        rejected = _tool(client, super_headers, "reject_factory_application",
                         application_id=rejected_application.application_id,
                         version=rejected_application.version, reason="资料不符")
        assert rejected["structuredContent"]["status"] == "rejected"
        users = _tool(client, super_headers, "list_users", role="factory")["structuredContent"]
        assert users["items"][0]["userId"] == applicant.user_id
        assert _tool(client, super_headers, "list_users", role="factory", page=0)[
            "isError"] is True
        disabled = _tool(client, super_headers, "set_user_enabled",
                         target_user_id=applicant.user_id,
                         version=users["items"][0]["version"], enabled=False)
        assert disabled["structuredContent"]["isEnabled"] is False
        assert _tool(client, super_headers, "set_user_enabled", target_user_id=super_id,
                     version=identity.get_user(user_id=super_id).version,
                     enabled=False)["isError"] is True

        with sessions() as session, session.begin():
            session.add_all([
                Notification(recipient_id=super_id, category="SHIPMENT",
                             event_type="shipment.submitted", target_type="shipment",
                             target_id="issue156-shipment", title="本人通知", summary="摘要",
                             target_path="/shipments/issue156-shipment", dedupe_key="issue156-own"),
                Product(product_id="issue156-product", source_i_id="ISSUE156",
                        name="测试产品", is_available=True,
                        image_object_key="products/issue156.png", image_cache_status="cached",
                        source_modified_at=datetime(2026, 9, 21),
                        first_synced_at=datetime(2026, 9, 21),
                        last_synced_at=datetime(2026, 9, 21)),
            ])
            session.flush()
            session.add(ProductVariant(
                variant_id="issue156-variant", product_id="issue156-product",
                source_sku_id="ISSUE156-SKU", properties_value="蓝色",
                is_available=True, source_modified_at=datetime(2026, 9, 21),
                first_synced_at=datetime(2026, 9, 21),
                last_synced_at=datetime(2026, 9, 21),
            ))
        own = _tool(client, super_headers, "list_notifications")["structuredContent"]
        assert own["total"] == 1
        assert own["items"][0]["targetId"] == "issue156-shipment"
        assert _tool(client, super_headers, "get_unread_count")["structuredContent"]["count"] == 1
        read = _tool(client, super_headers, "mark_notification_read",
                     notification_id=own["items"][0]["notificationId"])
        assert read["structuredContent"]["readAt"] is not None
        products = _tool(client, super_headers, "list_products")["structuredContent"]
        assert products["items"][0]["productId"] == "issue156-product"
        assert _tool(client, super_headers, "list_products", page=2, page_size=1)[
            "structuredContent"]["items"] == []
        image = _tool(client, super_headers, "get_product_image", product_id="issue156-product",
                      image_version=products["items"][0]["imageVersion"])
        assert base64.b64decode(image["content"][0]["data"]) == IMAGE
        assert image["content"][0]["mimeType"] == "image/png"
        assert _tool(client, super_headers, "get_product_image", product_id="issue156-product",
                     image_version="stale")["isError"] is True

    ordinary_app = create_app(database_url=test_database_url, identity_service=identity,
                              private_file_store=files)
    with TestClient(ordinary_app) as ordinary_client:
        ordinary_headers = _access(ordinary_client, "admin-code")
        assert _tool(ordinary_client, ordinary_headers, "list_users", role="admin")[
            "isError"] is True
        assert _tool(ordinary_client, ordinary_headers, "set_user_enabled",
                     target_user_id=super_id,
                     version=identity.get_user(user_id=super_id).version,
                     enabled=False)["isError"] is True
        assert _tool(ordinary_client, ordinary_headers, "list_users", role="factory")[
            "structuredContent"]["total"] == 1
        assert _tool(ordinary_client, ordinary_headers, "mark_notification_read",
                     notification_id=own["items"][0]["notificationId"])["isError"] is True
        assert _tool(ordinary_client, ordinary_headers, "list_notifications")[
            "structuredContent"]["total"] == 0
