from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.avatar import FakeAvatarStore
from app.adapters.identity import FakeFeishuIdentity
from app.adapters.wechat import FakeWechatIdentity, WechatProfile
from app.main import create_app
from app.modules.identity_access import FeishuProfile, IdentityAccessService


def clean_identity_tables(engine: Engine) -> None:
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


def test_web_identity_api_uses_secure_cookie_csrf_and_super_admin_authorization(
    test_database_engine: Engine,
    test_database_url: str,
) -> None:
    clean_identity_tables(test_database_engine)
    feishu = FakeFeishuIdentity(
        profiles={
            "applicant-code": FeishuProfile(
                subject="ou_applicant",
                display_name="煎饼",
                phone="13812345122",
            )
        },
        scope="tenant-a/app-a",
    )
    service = IdentityAccessService(
        sessionmaker(test_database_engine, class_=Session),
        feishu_identity=feishu,
        wechat_identity=FakeWechatIdentity(
            scope="test-appid", login_profiles={}, phone_codes={}
        ),
        avatar_store=FakeAvatarStore(bucket="test-private-avatar-bucket"),
        token_secret=b"test-token-secret-not-for-production",
        phone_encryption_secret=b"test-phone-encryption-secret",
        phone_digest_secret=b"test-phone-digest-secret",
    )
    app = create_app(database_url=test_database_url, identity_service=service)

    with TestClient(app, base_url="https://testserver") as client:
        started = client.get("/api/v1/auth/feishu/start", follow_redirects=False)
        assert started.status_code == 307
        state = parse_qs(urlparse(started.headers["location"]).query)["state"][0]
        callback = client.get(
            "/api/v1/auth/feishu/callback",
            params={"state": state, "code": "applicant-code"},
            follow_redirects=False,
        )
        assert callback.status_code == 303
        assert "HttpOnly" in callback.headers["set-cookie"]
        assert "Secure" in callback.headers["set-cookie"]
        original_refresh = client.cookies.get("ot_web_refresh")
        assert original_refresh

        client.cookies.delete("ot_web_session")
        client.cookies.delete("ot_csrf")
        refreshed = client.post("/api/v1/auth/refresh")
        assert refreshed.status_code == 204
        assert client.cookies.get("ot_web_session")
        assert client.cookies.get("ot_csrf")
        assert client.cookies.get("ot_web_refresh") != original_refresh

        with TestClient(app, base_url="https://testserver") as replay_client:
            replay_client.cookies.set("ot_web_refresh", original_refresh)
            assert replay_client.post("/api/v1/auth/refresh").status_code == 401

        me = client.get("/api/v1/me")
        assert me.status_code == 200
        assert me.json()["role"] is None
        csrf_token = client.cookies.get("ot_csrf")
        assert csrf_token

        missing_csrf = client.post("/api/v1/admin-applications", json={})
        assert missing_csrf.status_code == 403

        assert client.post(
            "/api/v1/sms/challenges",
            headers={"X-CSRF-Token": csrf_token},
            json={"phone": "13812345122"},
        ).status_code == 404
        submitted = client.post(
            "/api/v1/admin-applications",
            headers={"X-CSRF-Token": csrf_token},
            json={},
        )
        assert submitted.status_code == 201
        assert submitted.json()["status"] == "pending"

        forbidden = client.get("/api/v1/admin/admin-applications")
        assert forbidden.status_code == 403
        assert forbidden.json()["requestId"]

        refresh_before_logout = client.cookies.get("ot_web_refresh")
        logged_out = client.post(
            "/api/v1/auth/logout",
            headers={"X-CSRF-Token": client.cookies.get("ot_csrf") or ""},
        )
        assert logged_out.status_code == 204
        assert client.cookies.get("ot_web_refresh") is None
        assert refresh_before_logout
        with TestClient(app, base_url="https://testserver") as logged_out_client:
            logged_out_client.cookies.set("ot_web_refresh", refresh_before_logout)
            assert logged_out_client.post("/api/v1/auth/refresh").status_code == 401

    super_admin = service.bootstrap_super_admin(
        scope="tenant-a/app-a",
        profile=FeishuProfile(subject="ou_super", display_name="松子"),
        operator_source="deployment-command",
        request_id="req-bootstrap-super",
    )
    super_session = service.issue_session(user_id=super_admin.user_id, terminal="web")
    with TestClient(app, base_url="https://testserver") as super_client:
        super_client.cookies.set("ot_web_session", super_session.access_token)
        super_client.cookies.set("ot_csrf", super_session.csrf_token or "")
        listing = super_client.get("/api/v1/admin/admin-applications")
        assert listing.status_code == 200
        assert listing.json()["total"] == 1


def test_mini_identity_api_binds_refreshes_uploads_avatar_and_logs_out(
    test_database_engine: Engine,
    test_database_url: str,
) -> None:
    clean_identity_tables(test_database_engine)
    wechat = FakeWechatIdentity(
        scope="test-appid",
        login_profiles={
            "wx-login": WechatProfile(
                subject="openid-applicant",
                avatar_url="https://example.invalid/wechat-avatar.png",
            )
        },
        phone_codes={"wx-phone": "13812345122"},
    )
    avatar_store = FakeAvatarStore(bucket="test-private-avatar-bucket")
    service = IdentityAccessService(
        sessionmaker(test_database_engine, class_=Session),
        wechat_identity=wechat,
        avatar_store=avatar_store,
        token_secret=b"test-token-secret-not-for-production",
        phone_encryption_secret=b"test-phone-encryption-secret",
        phone_digest_secret=b"test-phone-digest-secret",
    )
    super_admin = service.bootstrap_super_admin(
        scope="tenant-a/app-a",
        profile=FeishuProfile(subject="ou_super", display_name="松子"),
        operator_source="deployment-command",
        request_id="req-bootstrap-super",
    )
    applicant = service.resolve_feishu_identity(
        scope="tenant-a/app-a",
        profile=FeishuProfile(
            subject="ou_applicant",
            display_name="煎饼",
            phone="13812345122",
        ),
        request_id="req-create-applicant",
    )
    application = service.submit_admin_application(
        user_id=applicant.user_id,
        request_id="req-submit-application",
    )
    service.approve_admin_application(
        actor_id=super_admin.user_id,
        application_id=application.application_id,
        expected_version=application.version,
        request_id="req-approve-application",
    )
    app = create_app(database_url=test_database_url, identity_service=service)

    with TestClient(app, base_url="https://testserver") as client:
        login = client.post("/api/v1/mini/auth/wechat", json={"code": "wx-login"})
        assert login.status_code == 200
        assert login.json()["status"] == "phone_required"
        bound = client.post(
            "/api/v1/mini/auth/phone",
            json={
                "bindingToken": login.json()["bindingToken"],
                "phoneCode": "wx-phone",
            },
        )
        assert bound.status_code == 200
        assert bound.json()["user"]["miniAvatarExternalUrl"] == (
            "https://example.invalid/wechat-avatar.png"
        )
        access_token = bound.json()["session"]["accessToken"]
        refresh_token = bound.json()["session"]["refreshToken"]
        authorization = {"Authorization": f"Bearer {access_token}"}
        me = client.get("/api/v1/me", headers=authorization)
        assert me.status_code == 200
        assert me.json()["userId"] == applicant.user_id

        avatar = client.post(
            "/api/v1/mini/me/avatar",
            headers={**authorization, "Idempotency-Key": "avatar-api-001"},
            files={
                "avatar": (
                    "avatar.png",
                    b"\x89PNG\r\n\x1a\napi-avatar",
                    "image/png",
                )
            },
        )
        assert avatar.status_code == 200
        assert avatar_store.object_count == 1
        loaded_avatar = client.get("/api/v1/mini/me/avatar", headers=authorization)
        assert loaded_avatar.status_code == 200
        assert loaded_avatar.content == b"\x89PNG\r\n\x1a\napi-avatar"
        assert loaded_avatar.headers["cache-control"] == "private, no-store"

        refreshed = client.post(
            "/api/v1/mini/auth/refresh",
            json={"refreshToken": refresh_token},
        )
        assert refreshed.status_code == 200
        refreshed_access = refreshed.json()["accessToken"]
        logged_out = client.post(
            "/api/v1/mini/auth/logout",
            headers={"Authorization": f"Bearer {refreshed_access}"},
        )
        assert logged_out.status_code == 204
        after_logout = client.get(
            "/api/v1/me",
            headers={"Authorization": f"Bearer {refreshed_access}"},
        )
        assert after_logout.status_code == 401

        repeated = client.post("/api/v1/mini/auth/wechat", json={"code": "wx-login"})
        assert repeated.status_code == 200
        assert repeated.json()["status"] == "authenticated"
        assert repeated.json()["user"]["userId"] == applicant.user_id
