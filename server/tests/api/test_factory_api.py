from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.wechat import FakeWechatIdentity, WechatProfile
from app.main import create_app
from app.modules.factory_access import FactoryAccessService
from app.modules.identity_access import FeishuProfile, IdentityAccessService


def clean_factory_tables(engine: Engine) -> None:
    with engine.begin() as connection:
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
        connection.execute(text("DELETE FROM users"))
        connection.execute(text("DELETE FROM factory_contacts"))
        connection.execute(text("DELETE FROM factories"))


def test_factory_api_creates_reviews_and_disables_factory_user(
    test_database_engine: Engine,
    test_database_url: str,
) -> None:
    clean_factory_tables(test_database_engine)
    sessions = sessionmaker(test_database_engine, class_=Session)
    wechat = FakeWechatIdentity(
        scope="test-appid",
        login_profiles={"wx-login": WechatProfile(subject="openid-factory-api")},
        phone_codes={"wx-phone": "13912345678"},
    )
    identity = IdentityAccessService(
        sessions,
        wechat_identity=wechat,
        token_secret=b"test-token-secret-not-for-production",
        phone_encryption_secret=b"test-phone-encryption-secret",
        phone_digest_secret=b"test-phone-digest-secret",
    )
    factories = FactoryAccessService(sessions)
    admin = identity.resolve_feishu_identity(
        scope="tenant-a/app-a",
        profile=FeishuProfile(
            subject="ou_factory_api_admin",
            display_name="松子",
            phone="13812345122",
        ),
        request_id="req-login-api-admin",
        auto_grant_admin=True,
    )
    assert admin.is_super_admin is False
    web_session = identity.issue_session(user_id=admin.user_id, terminal="web")
    app = create_app(
        database_url=test_database_url,
        identity_service=identity,
        factory_service=factories,
    )

    with TestClient(app, base_url="https://testserver") as admin_client:
        admin_client.cookies.set("ot_web_session", web_session.access_token)
        admin_client.cookies.set("ot_csrf", web_session.csrf_token or "")
        created = admin_client.post(
            "/api/v1/admin/factories",
            headers={"X-CSRF-Token": web_session.csrf_token or ""},
            json={
                "supplierNumber": "a10",
                "factoryName": "禹帆",
                "factoryCode": "yf",
                "legalName": "温岭市新河禹帆制帽厂",
                "address": "浙江省温岭市",
                "legalRepresentative": "徐陈杰",
                "contacts": [{"name": "王超", "phone": "13858645122"}],
            },
        )
        assert created.status_code == 201
        factory_id = created.json()["factoryId"]
        assert created.json()["supplierNumber"] == "A10"

        listed = admin_client.get("/api/v1/admin/factories", params={"keyword": "王超"})
        assert listed.status_code == 200
        assert listed.json()["total"] == 1

    with TestClient(app, base_url="https://testserver") as mini_client:
        login = mini_client.post("/api/v1/mini/auth/wechat", json={"code": "wx-login"})
        phone = mini_client.post(
            "/api/v1/mini/auth/phone",
            json={
                "bindingToken": login.json()["bindingToken"],
                "phoneCode": "wx-phone",
            },
        )
        assert phone.status_code == 200
        assert phone.json()["status"] == "factory_application_required"
        applicant_token = phone.json()["session"]["accessToken"]
        options = mini_client.get(
            "/api/v1/factories",
            headers={"Authorization": f"Bearer {applicant_token}"},
        )
        assert options.status_code == 200
        assert options.json()["items"][0] == {
            "factoryId": factory_id,
            "supplierNumber": "A10",
            "factoryName": "禹帆",
        }
        submitted = mini_client.post(
            "/api/v1/factory-applications",
            headers={"Authorization": f"Bearer {applicant_token}"},
            json={
                "realName": "张师傅",
                "position": "employee",
                "factoryId": factory_id,
            },
        )
        assert submitted.status_code == 201
        application_id = submitted.json()["applicationId"]
        application_version = submitted.json()["version"]

    with TestClient(app, base_url="https://testserver") as admin_client:
        admin_client.cookies.set("ot_web_session", web_session.access_token)
        admin_client.cookies.set("ot_csrf", web_session.csrf_token or "")
        detail = admin_client.get(
            f"/api/v1/admin/factory-applications/{application_id}"
        )
        assert detail.status_code == 200
        assert detail.json()["factoryContacts"][0]["name"] == "王超"
        approved = admin_client.post(
            f"/api/v1/admin/factory-applications/{application_id}/approve",
            headers={"X-CSRF-Token": web_session.csrf_token or ""},
            json={"version": application_version, "factoryId": factory_id},
        )
        assert approved.status_code == 200

    with TestClient(app, base_url="https://testserver") as mini_client:
        assert (
            mini_client.get(
                "/api/v1/me",
                headers={"Authorization": f"Bearer {applicant_token}"},
            ).status_code
            == 401
        )
        relogin = mini_client.post("/api/v1/mini/auth/wechat", json={"code": "wx-login"})
        assert relogin.json()["status"] == "authenticated"
        assert relogin.json()["user"]["factoryId"] == factory_id
        current = mini_client.get(
            "/api/v1/me",
            headers={"Authorization": f"Bearer {relogin.json()['session']['accessToken']}"},
        )
        assert current.status_code == 200
        assert current.json()["factoryName"] == "禹帆"
        factory_user_id = relogin.json()["user"]["userId"]
        factory_user_version = relogin.json()["user"]["version"]

    with TestClient(app, base_url="https://testserver") as admin_client:
        admin_client.cookies.set("ot_web_session", web_session.access_token)
        admin_client.cookies.set("ot_csrf", web_session.csrf_token or "")
        users = admin_client.get("/api/v1/admin/users", params={"role": "factory"})
        assert users.status_code == 200
        assert users.json()["items"][0]["factoryName"] == "禹帆"
        disabled = admin_client.post(
            f"/api/v1/admin/users/{factory_user_id}/disable",
            headers={"X-CSRF-Token": web_session.csrf_token or ""},
            json={"version": factory_user_version},
        )
        assert disabled.status_code == 200
        assert disabled.json()["isEnabled"] is False
