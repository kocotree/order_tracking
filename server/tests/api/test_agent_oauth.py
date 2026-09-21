import base64
import hashlib
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.identity import FakeFeishuIdentity
from app.main import create_app
from app.modules.identity_access import FeishuProfile, IdentityAccessService

RESOURCE = "http://testserver/mcp"
CLIENT_ID = "codex-company-test"
CALLBACK = "http://127.0.0.1:49152/callback/codexNonce123"
VERIFIER = "v" * 43
CHALLENGE = base64.urlsafe_b64encode(
    hashlib.sha256(VERIFIER.encode()).digest()
).rstrip(b"=").decode()


def _client(engine: Engine, database_url: str, monkeypatch) -> TestClient:
    monkeypatch.setenv("ORDER_TRACKING_MCP_PUBLIC_URL", RESOURCE)
    monkeypatch.setenv("ORDER_TRACKING_MCP_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("ORDER_TRACKING_WEB_COOKIE_SECURE", "false")
    monkeypatch.setenv("ORDER_TRACKING_IDENTITY_TOKEN_SECRET", "agent-test-token-secret")
    service = IdentityAccessService(
        sessionmaker(engine, class_=Session),
        feishu_identity=FakeFeishuIdentity(
            profiles={"agent-code": FeishuProfile(
                subject="agent-user", display_name="Test Admin", phone="13812345122",
            )},
            scope="tenant-test/app-test",
        ),
        token_secret=b"agent-test-token-secret",
        phone_encryption_secret=b"agent-test-phone-encryption",
        phone_digest_secret=b"agent-test-phone-digest",
    )
    return TestClient(create_app(database_url=database_url, identity_service=service))


def _login(client: TestClient) -> None:
    started = client.get("/api/v1/auth/feishu/start", follow_redirects=False)
    state = parse_qs(urlparse(started.headers["location"]).query)["state"][0]
    completed = client.get(
        "/api/v1/auth/feishu/callback",
        params={"state": state, "code": "agent-code"},
        follow_redirects=False,
    )
    assert completed.status_code == 303


def _code(client: TestClient) -> str:
    started = client.get(
        "/oauth/authorize",
        params={
            "client_id": CLIENT_ID, "redirect_uri": CALLBACK, "resource": RESOURCE,
            "scope": "order_tracking.admin", "state": "state-for-agent-test",
            "code_challenge": CHALLENGE, "code_challenge_method": "S256",
            "response_type": "code",
        },
        follow_redirects=False,
    )
    assert started.status_code == 303
    completed = client.get(started.headers["location"], follow_redirects=False)
    assert completed.status_code == 303
    return parse_qs(urlparse(completed.headers["location"]).query)["code"][0]


def _exchange(client: TestClient, code: str, **overrides: str):
    payload = {
        "grant_type": "authorization_code", "client_id": CLIENT_ID,
        "redirect_uri": CALLBACK, "resource": RESOURCE,
        "code": code, "code_verifier": VERIFIER,
    }
    payload.update(overrides)
    return client.post("/oauth/token", data=payload)


def test_agent_oauth_and_mcp_query_share_web_logout(
    test_database_engine: Engine, test_database_url: str, monkeypatch
) -> None:
    with _client(test_database_engine, test_database_url, monkeypatch) as client:
        _login(client)
        assert client.get("/.well-known/oauth-authorization-server").status_code == 200
        assert client.get("/.well-known/oauth-protected-resource/mcp").status_code == 200
        assert client.post("/mcp", json={}).status_code == 401
        code = _code(client)
        issued = _exchange(client, code)
        assert issued.status_code == 200
        access = issued.json()["access_token"]
        assert _exchange(client, code).status_code == 400
        headers = {
            "Authorization": f"Bearer {access}",
            "Accept": "application/json, text/event-stream",
        }
        initialized = client.post("/mcp", json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                       "clientInfo": {"name": "test", "version": "1"}},
        }, headers=headers)
        assert initialized.status_code == 200
        listed = client.post("/mcp", json={
            "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {},
        }, headers=headers)
        assert listed.status_code == 200
        assert {tool["name"] for tool in listed.json()["result"]["tools"]} >= {
            "get_me", "get_dashboard", "list_orders", "get_order",
            "get_order_audit", "logout_shared_session",
        }
        queried = client.post("/mcp", json={
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "list_orders", "arguments": {}},
        }, headers=headers)
        assert queried.status_code == 200
        assert "error" not in queried.json()
        assert queried.json()["result"].get("isError") is not True
        assert queried.json()["result"]["structuredContent"]["total"] == 0
        csrf = client.cookies.get("ot_csrf")
        assert csrf is not None
        logout = client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
        assert logout.status_code == 204
        assert client.post("/mcp", json={
            "jsonrpc": "2.0", "id": 4, "method": "tools/list", "params": {},
        }, headers=headers).status_code == 401


def test_agent_oauth_rejects_wrong_client_resource_pkce_and_refresh_replay(
    test_database_engine: Engine, test_database_url: str, monkeypatch
) -> None:
    with _client(test_database_engine, test_database_url, monkeypatch) as client:
        _login(client)
        bad_client = client.get("/oauth/authorize", params={
            "client_id": "unknown", "redirect_uri": CALLBACK, "resource": RESOURCE,
            "scope": "order_tracking.admin", "state": "state-for-agent-test",
            "code_challenge": CHALLENGE, "code_challenge_method": "S256",
            "response_type": "code",
        })
        assert bad_client.status_code == 401
        code = _code(client)
        assert _exchange(client, code, resource="https://wrong.example/mcp").status_code == 400
        assert _exchange(client, code, code_verifier="x" * 43).status_code == 400
        assert _exchange(client, code, client_secret="unexpected").status_code == 401
        issued = _exchange(client, code)
        assert issued.status_code == 200
        refresh = issued.json()["refresh_token"]
        payload = {
            "grant_type": "refresh_token", "client_id": CLIENT_ID,
            "resource": RESOURCE, "refresh_token": refresh,
        }
        assert client.post("/oauth/token", data=payload).status_code == 200
        assert client.post("/oauth/token", data=payload).status_code == 400
        assert client.get("/api/v1/me").status_code == 401


def test_agent_oauth_resumes_after_feishu_login_and_rejects_wrong_callback(
    test_database_engine: Engine, test_database_url: str, monkeypatch
) -> None:
    with _client(test_database_engine, test_database_url, monkeypatch) as client:
        params = {
            "client_id": CLIENT_ID, "redirect_uri": CALLBACK,
            "resource": RESOURCE, "scope": "order_tracking.admin",
            "state": "state-for-agent-test", "code_challenge": CHALLENGE,
            "code_challenge_method": "S256", "response_type": "code",
        }
        rejected = client.get(
            "/oauth/authorize", params={**params, "redirect_uri": "https://wrong.example/callback"}
        )
        assert rejected.status_code == 400
        rejected_resources = client.get("/oauth/authorize", params=[
            *[(name, value) for name, value in params.items()],
            ("resource", "https://wrong.example/mcp"),
        ])
        assert rejected_resources.status_code == 400
        started = client.get("/oauth/authorize", params=[
            *[(name, value) for name, value in params.items()],
            ("resource", RESOURCE),
        ], follow_redirects=False)
        pending = client.get(started.headers["location"], follow_redirects=False)
        assert pending.status_code == 303
        assert pending.headers["location"].startswith("/api/v1/auth/feishu/start?")
        feishu = client.get(pending.headers["location"], follow_redirects=False)
        state = parse_qs(urlparse(feishu.headers["location"]).query)["state"][0]
        signed_in = client.get(
            "/api/v1/auth/feishu/callback",
            params={"state": state, "code": "agent-code"},
            follow_redirects=False,
        )
        assert signed_in.headers["location"].startswith("/oauth/authorize?")
        completed = client.get(signed_in.headers["location"], follow_redirects=False)
        code = parse_qs(urlparse(completed.headers["location"]).query)["code"][0]
        assert _exchange(client, code).status_code == 200
