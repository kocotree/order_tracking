from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.main import create_app


def clean_identity_tables(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(text("UPDATE users SET mini_avatar_file_id = NULL"))
        connection.execute(text("DELETE FROM stored_files"))
        connection.execute(text("DELETE FROM mini_login_attempts"))
        connection.execute(text("UPDATE admin_applications SET previous_application_id = NULL"))
        connection.execute(text("DELETE FROM admin_applications"))
        connection.execute(text("DELETE FROM sms_challenges"))
        connection.execute(text("DELETE FROM user_sessions"))
        connection.execute(text("DELETE FROM oauth_states"))
        connection.execute(text("DELETE FROM external_identities"))
        connection.execute(text("DELETE FROM users"))


def test_local_demo_completes_cross_terminal_identity_flow_over_public_http(
    test_database_engine: Engine,
    test_database_url: str,
    monkeypatch,
) -> None:
    clean_identity_tables(test_database_engine)
    monkeypatch.setenv("ORDER_TRACKING_APP_ENV", "local_demo")
    monkeypatch.setenv("ORDER_TRACKING_IDENTITY_TOKEN_SECRET", "local-demo-test-token")
    monkeypatch.setenv("ORDER_TRACKING_PHONE_ENCRYPTION_SECRET", "local-demo-test-phone")
    monkeypatch.setenv("ORDER_TRACKING_PHONE_DIGEST_SECRET", "local-demo-test-digest")

    app = create_app(database_url=test_database_url)

    def log_in(client: TestClient, identity: str, return_to: str = "/") -> None:
        started = client.get(
            "/api/v1/auth/feishu/start",
            params={"returnTo": return_to},
            follow_redirects=False,
        )
        assert started.status_code == 307
        assert started.headers["location"].startswith(
            "/api/v1/local-demo/feishu-authorize?"
        )

        chooser = client.get(started.headers["location"])
        assert chooser.status_code == 200
        assert "仅限本机演示" in chooser.text
        assert "123456" in chooser.text

        selected = client.get(
            f"{started.headers['location']}&identity={identity}",
            follow_redirects=False,
        )
        assert selected.status_code == 303
        callback = client.get(selected.headers["location"], follow_redirects=False)
        assert callback.status_code == 303
        assert callback.headers["location"] == return_to
        assert "Secure" not in callback.headers["set-cookie"]
        assert client.get("/api/v1/me").status_code == 200

    def log_out(client: TestClient) -> None:
        csrf_token = client.cookies.get("ot_csrf")
        assert csrf_token
        response = client.post(
            "/api/v1/auth/logout",
            headers={"X-CSRF-Token": csrf_token},
        )
        assert response.status_code == 204

    with TestClient(app, base_url="http://testserver") as client:
        log_in(client, "applicant", "/admin-apply")
        applicant = client.get("/api/v1/me").json()
        assert applicant["displayName"] == "演示申请人"
        assert applicant["role"] is None

        csrf_token = client.cookies.get("ot_csrf")
        assert csrf_token
        challenge = client.post(
            "/api/v1/sms/challenges",
            headers={"X-CSRF-Token": csrf_token},
            json={"phone": "10000000000"},
        )
        assert challenge.status_code == 201
        submitted = client.post(
            "/api/v1/admin-applications",
            headers={"X-CSRF-Token": csrf_token},
            json={
                "challengeId": challenge.json()["challengeId"],
                "verificationCode": "123456",
            },
        )
        assert submitted.status_code == 201
        assert submitted.json()["status"] == "pending"
        log_out(client)

        log_in(client, "super")
        super_admin = client.get("/api/v1/me").json()
        assert super_admin["isSuperAdmin"] is True
        listing = client.get("/api/v1/admin/admin-applications")
        assert listing.status_code == 200
        application = listing.json()["items"][0]
        csrf_token = client.cookies.get("ot_csrf")
        assert csrf_token
        approved = client.post(
            f"/api/v1/admin/admin-applications/{application['applicationId']}/approve",
            headers={"X-CSRF-Token": csrf_token},
            json={"version": application["version"]},
        )
        assert approved.status_code == 200
        log_out(client)

        log_in(client, "applicant")
        approved_applicant = client.get("/api/v1/me").json()
        assert approved_applicant["role"] == "admin"
        assert approved_applicant["isSuperAdmin"] is False
        forbidden = client.get("/api/v1/admin/admin-applications")
        assert forbidden.status_code == 403
        log_out(client)

        mini_login = client.post(
            "/api/v1/mini/auth/wechat",
            json={"code": "any-local-wechat-login-code"},
        )
        assert mini_login.status_code == 200
        assert mini_login.json()["status"] == "phone_required"
        mini_bound = client.post(
            "/api/v1/mini/auth/phone",
            json={
                "bindingToken": mini_login.json()["bindingToken"],
                "phoneCode": "any-local-wechat-phone-code",
            },
        )
        assert mini_bound.status_code == 200
        assert mini_bound.json()["status"] == "authenticated"
        assert mini_bound.json()["user"]["userId"] == applicant["userId"]


def test_local_demo_routes_are_absent_in_normal_development(
    test_database_url: str,
    monkeypatch,
) -> None:
    monkeypatch.setenv("ORDER_TRACKING_APP_ENV", "development")
    app = create_app(database_url=test_database_url)

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/local-demo/feishu-authorize",
            params={"state": "not-a-real-state"},
        )

    assert response.status_code == 404
