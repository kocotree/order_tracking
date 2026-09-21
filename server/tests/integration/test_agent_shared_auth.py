import base64
import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.identity import FeishuProfile
from app.db.models import AdminSharedAuthorization, User
from app.modules.identity_access import IdentityAccessService, SessionInvalid
from app.modules.identity_access.agent_oauth import AgentOAuthService, OAuthInvalid

RESOURCE = "http://testserver/mcp"
CLIENT = "codex-company-test"
CALLBACK = "http://127.0.0.1:49152/callback/codexNonce123"
VERIFIER = "v" * 43
CHALLENGE = base64.urlsafe_b64encode(
    hashlib.sha256(VERIFIER.encode()).digest()
).rstrip(b"=").decode()


def _setup(engine: Engine, now: list[datetime]):
    sessions = sessionmaker(engine, class_=Session)
    def clock() -> datetime:
        return now[0]
    identity = IdentityAccessService(
        sessions, clock=clock,
        token_secret=b"agent-shared-test-secret",
        phone_encryption_secret=b"agent-shared-phone-key",
        phone_digest_secret=b"agent-shared-phone-digest",
    )
    oauth = AgentOAuthService(
        sessions, resource=RESOURCE, client_id=CLIENT,
        token_secret=b"agent-shared-test-secret", clock=clock,
    )
    user = identity.resolve_feishu_identity(
        scope="tenant-test/app-test",
        profile=FeishuProfile(
            subject="agent-test-user", display_name="Test Admin", phone="13812345122",
        ),
        request_id="create-agent-test-user", auto_grant_admin=True,
    )
    web = identity.issue_session(user_id=user.user_id, terminal="web")
    user_id, auth_id = identity.web_authorization_id(token=web.access_token)
    request_id, nonce = oauth.begin_authorization(
        client_id=CLIENT, redirect_uri=CALLBACK, resource=RESOURCE,
        scope="order_tracking.admin", state="agent-test-state",
        code_challenge=CHALLENGE, code_challenge_method="S256", response_type="code",
    )
    _, _, code = oauth.finish_authorization(
        request_id=request_id, browser_nonce=nonce, user_id=user_id, auth_id=auth_id,
    )
    tokens = oauth.exchange_code(
        code=code, client_id=CLIENT, redirect_uri=CALLBACK,
        verifier=VERIFIER, resource=RESOURCE,
    )
    return identity, oauth, user_id, auth_id, web, tokens


def test_web_and_agent_activity_share_30_day_eligibility(test_database_engine: Engine) -> None:
    now = [datetime(2026, 9, 1, tzinfo=UTC)]
    identity, oauth, user_id, auth_id, web, tokens = _setup(test_database_engine, now)
    assert web.refresh_token is not None
    refresh = str(tokens["refresh_token"])
    now[0] += timedelta(days=29)
    rotated = oauth.refresh(refresh_token=refresh, client_id=CLIENT, resource=RESOURCE)
    with Session(test_database_engine) as session:
        shared = session.scalar(select(AdminSharedAuthorization).where(
            AdminSharedAuthorization.auth_id == auth_id
        ))
        assert shared is not None
        assert shared.last_activity_at == datetime(2026, 9, 1)
    oauth.record_tool_success(
        auth_id=auth_id, user_id=user_id, tool="list_orders", request_id="agent-read",
    )
    now[0] += timedelta(days=2)
    web_refreshed = identity.refresh_web_session(refresh_token=web.refresh_token)
    assert web_refreshed.refresh_token is not None
    identity.authenticate_session(token=web_refreshed.access_token, terminal="web")
    now[0] += timedelta(days=29)
    assert "access_token" in oauth.refresh(
        refresh_token=str(rotated["refresh_token"]), client_id=CLIENT, resource=RESOURCE
    )


def test_refresh_does_not_keep_expired_authorization_alive(test_database_engine: Engine) -> None:
    now = [datetime(2026, 9, 1, tzinfo=UTC)]
    identity, oauth, user_id, auth_id, web, tokens = _setup(test_database_engine, now)
    assert web.refresh_token is not None
    now[0] += timedelta(days=29)
    rotated = oauth.refresh(
        refresh_token=str(tokens["refresh_token"]), client_id=CLIENT, resource=RESOURCE
    )
    now[0] += timedelta(days=2)
    with pytest.raises(SessionInvalid):
        identity.refresh_web_session(refresh_token=web.refresh_token)
    with pytest.raises(OAuthInvalid):
        oauth.refresh(
            refresh_token=str(rotated["refresh_token"]), client_id=CLIENT, resource=RESOURCE
        )
    new_web = identity.issue_session(user_id=user_id, terminal="web")
    _, new_auth_id = identity.web_authorization_id(token=new_web.access_token)
    assert new_auth_id != auth_id
    assert oauth.verify_access(str(rotated["access_token"])) is None


@pytest.mark.parametrize("change", ["disabled", "factory"])
def test_admin_permission_is_rechecked_for_agent_tokens(
    test_database_engine: Engine, change: str
) -> None:
    now = [datetime(2026, 9, 1, tzinfo=UTC)]
    identity, oauth, user_id, _auth_id, web, tokens = _setup(test_database_engine, now)
    with Session(test_database_engine) as session, session.begin():
        user = session.get(User, user_id)
        assert user is not None
        if change == "disabled":
            user.is_enabled = False
        else:
            user.role = "factory"
    assert oauth.verify_access(str(tokens["access_token"])) is None
    with pytest.raises(OAuthInvalid):
        oauth.refresh(
            refresh_token=str(tokens["refresh_token"]), client_id=CLIENT, resource=RESOURCE
        )
    with pytest.raises(SessionInvalid):
        identity.web_authorization_id(token=web.access_token)


def test_web_logout_wins_against_agent_refresh_and_revokes_other_devices(
    test_database_engine: Engine,
) -> None:
    now = [datetime(2026, 9, 1, tzinfo=UTC)]
    identity, oauth, user_id, auth_id, web, tokens = _setup(test_database_engine, now)
    other_web = identity.issue_session(user_id=user_id, terminal="web")
    assert identity.web_authorization_id(token=other_web.access_token)[1] == auth_id
    with ThreadPoolExecutor(max_workers=2) as pool:
        logout = pool.submit(
            identity.logout_session, token=web.access_token,
            terminal="web", request_id="web-logout",
        )
        refresh = pool.submit(
            oauth.refresh, refresh_token=str(tokens["refresh_token"]),
            client_id=CLIENT, resource=RESOURCE,
        )
        logout.result(timeout=10)
        try:
            refreshed = refresh.result(timeout=10)
        except OAuthInvalid:
            refreshed = None
    with pytest.raises(SessionInvalid):
        identity.authenticate_session(token=other_web.access_token, terminal="web")
    assert oauth.verify_access(str(tokens["access_token"])) is None
    if refreshed is not None:
        assert oauth.verify_access(str(refreshed["access_token"])) is None


def test_migration_links_only_live_admin_web_sessions_without_resetting_activity(
    test_database_engine: Engine, test_database_url: str
) -> None:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", test_database_url)
    command.downgrade(config, "20260916_0040")
    now = datetime.now(UTC).replace(tzinfo=None)
    original_activity = now - timedelta(days=5)
    with test_database_engine.begin() as connection:
        for user_id, role in (("migration-admin", "admin"), ("migration-factory", "factory")):
            connection.execute(text("""
                INSERT INTO users (user_id, role, is_enabled, feishu_display_name)
                VALUES (:user_id, :role, 1, 'Test User')
            """), {"user_id": user_id, "role": role})
        for session_id, user_id, activity, revoked in (
            ("migration-live", "migration-admin", original_activity, None),
            ("migration-old", "migration-admin", now - timedelta(days=31), None),
            ("migration-revoked", "migration-admin", now, now),
            ("migration-factory-session", "migration-factory", now, None),
        ):
            connection.execute(text("""
                INSERT INTO user_sessions
                (session_id, user_id, terminal, token_digest, expires_at,
                 refresh_expires_at, last_activity_at, revoked_at)
                VALUES (:session_id, :user_id, 'web', :token_digest, :expires_at,
                        :refresh_expires_at, :activity, :revoked)
            """), {
                "session_id": session_id, "user_id": user_id,
                "token_digest": hashlib.sha256(session_id.encode()).hexdigest(),
                "expires_at": now + timedelta(hours=1),
                "refresh_expires_at": now + timedelta(days=10),
                "activity": activity, "revoked": revoked,
            })
    command.upgrade(config, "head")
    with test_database_engine.connect() as connection:
        rows = connection.execute(text("""
            SELECT session_id, shared_auth_id FROM user_sessions
            WHERE session_id LIKE 'migration-%'
        """)).all()
        linked = dict(rows)
        assert linked["migration-live"] is not None
        assert linked["migration-old"] == linked["migration-live"]
        assert linked["migration-revoked"] is None
        assert linked["migration-factory-session"] is None
        shared_activity = connection.execute(text("""
            SELECT last_activity_at FROM admin_shared_authorizations WHERE auth_id = :auth_id
        """), {"auth_id": linked["migration-live"]}).scalar_one()
        assert shared_activity == original_activity
