import base64
import hashlib
import hmac
import re
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import (
    AdminSharedAuthorization,
    AgentOAuthGrant,
    AgentOAuthRequest,
    AgentOAuthToken,
    AuditLog,
    User,
)

SCOPE = "order_tracking.admin"


class OAuthInvalid(ValueError):
    def __init__(self, error: str = "invalid_request") -> None:
        self.error = error
        super().__init__(error)


class AgentOAuthService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        resource: str,
        client_id: str,
        token_secret: bytes,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._sessions = session_factory
        self.resource = resource
        self.client_id = client_id
        self._secret = token_secret
        self._clock = clock

    def _now(self) -> datetime:
        value = self._clock()
        return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value

    def _digest(self, value: str) -> str:
        return hmac.new(self._secret, value.encode(), hashlib.sha256).hexdigest()

    def _client(self, client_id: str) -> None:
        if not hmac.compare_digest(client_id, self.client_id):
            raise OAuthInvalid("invalid_client")

    def _resource(self, resource: str) -> None:
        if resource != self.resource:
            raise OAuthInvalid("invalid_target")

    @staticmethod
    def _redirect(redirect_uri: str) -> None:
        try:
            parsed = urlsplit(redirect_uri)
            valid_port = parsed.port is not None and 1 <= parsed.port <= 65535
        except ValueError as error:
            raise OAuthInvalid() from error
        if (
            parsed.scheme != "http"
            or parsed.hostname != "127.0.0.1"
            or not valid_port
            or re.fullmatch(r"/callback/[A-Za-z0-9_-]{8,128}", parsed.path) is None
            or parsed.query
            or parsed.fragment
            or parsed.username
            or parsed.password
        ):
            raise OAuthInvalid()

    def begin_authorization(
        self,
        *,
        client_id: str,
        redirect_uri: str,
        resource: str,
        scope: str,
        state: str,
        code_challenge: str,
        code_challenge_method: str,
        response_type: str,
    ) -> tuple[str, str]:
        self._client(client_id)
        self._redirect(redirect_uri)
        self._resource(resource)
        if (
            scope != SCOPE
            or response_type != "code"
            or code_challenge_method != "S256"
            or not 8 <= len(state) <= 500
            or re.fullmatch(r"[A-Za-z0-9_-]{43,128}", code_challenge) is None
        ):
            raise OAuthInvalid()
        nonce = secrets.token_urlsafe(32)
        request_id = str(uuid4())
        with self._sessions() as session, session.begin():
            session.add(AgentOAuthRequest(
                request_id=request_id,
                client_id=client_id,
                redirect_uri=redirect_uri,
                resource=resource,
                scope=scope,
                state=state,
                code_challenge=code_challenge,
                browser_digest=self._digest(nonce),
                expires_at=self._now() + timedelta(minutes=5),
            ))
        return request_id, nonce

    def finish_authorization(
        self, *, request_id: str, browser_nonce: str, user_id: str, auth_id: str
    ) -> tuple[str, str, str]:
        now = self._now()
        code = secrets.token_urlsafe(32)
        with self._sessions() as session, session.begin():
            pending = session.scalar(
                select(AgentOAuthRequest)
                .where(AgentOAuthRequest.request_id == request_id)
                .with_for_update()
            )
            if (
                pending is None
                or pending.used_at is not None
                or pending.code_digest is not None
                or pending.expires_at <= now
                or not hmac.compare_digest(pending.browser_digest, self._digest(browser_nonce))
            ):
                raise OAuthInvalid()
            self._active_shared(session, auth_id, user_id, now, lock=True)
            pending.user_id = user_id
            pending.shared_auth_id = auth_id
            pending.code_digest = self._digest(code)
            return pending.redirect_uri, pending.state, code

    @staticmethod
    def _active_shared(
        session: Session, auth_id: str, user_id: str, now: datetime, *, lock: bool = False
    ) -> AdminSharedAuthorization:
        statement = select(AdminSharedAuthorization).where(
            AdminSharedAuthorization.auth_id == auth_id
        )
        shared = session.scalar(statement.with_for_update() if lock else statement)
        user = session.get(User, user_id)
        if (
            shared is None
            or shared.user_id != user_id
            or shared.revoked_at is not None
            or shared.last_activity_at + timedelta(days=30) <= now
            or user is None
            or user.role != "admin"
            or not user.is_enabled
        ):
            raise OAuthInvalid("invalid_grant")
        return shared

    def _issue_pair(
        self, session: Session, grant: AgentOAuthGrant, now: datetime
    ) -> dict[str, str | int]:
        access = secrets.token_urlsafe(32)
        refresh = secrets.token_urlsafe(32)
        session.add_all([
            AgentOAuthToken(
                token_id=str(uuid4()), grant_id=grant.grant_id,
                token_digest=self._digest(access), kind="access",
                expires_at=now + timedelta(minutes=15),
            ),
            AgentOAuthToken(
                token_id=str(uuid4()), grant_id=grant.grant_id,
                token_digest=self._digest(refresh), kind="refresh", expires_at=None,
            ),
        ])
        return {
            "access_token": access,
            "refresh_token": refresh,
            "token_type": "Bearer",
            "expires_in": 900,
            "scope": SCOPE,
        }

    def exchange_code(
        self, *, code: str, client_id: str, redirect_uri: str, verifier: str, resource: str
    ) -> dict[str, str | int]:
        self._client(client_id)
        self._redirect(redirect_uri)
        self._resource(resource)
        if re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", verifier) is None:
            raise OAuthInvalid("invalid_grant")
        now = self._now()
        with self._sessions() as session, session.begin():
            pending = session.scalar(
                select(AgentOAuthRequest)
                .where(AgentOAuthRequest.code_digest == self._digest(code))
                .with_for_update()
            )
            challenge = base64.urlsafe_b64encode(
                hashlib.sha256(verifier.encode()).digest()
            ).rstrip(b"=").decode()
            if (
                pending is None
                or pending.used_at is not None
                or pending.expires_at <= now
                or pending.client_id != client_id
                or pending.redirect_uri != redirect_uri
                or pending.resource != resource
                or not hmac.compare_digest(pending.code_challenge, challenge)
                or pending.user_id is None
                or pending.shared_auth_id is None
            ):
                raise OAuthInvalid("invalid_grant")
            self._active_shared(session, pending.shared_auth_id, pending.user_id, now, lock=True)
            pending.used_at = now
            grant = AgentOAuthGrant(
                grant_id=str(uuid4()), user_id=pending.user_id,
                shared_auth_id=pending.shared_auth_id, client_id=client_id,
                resource=resource, scope=SCOPE,
            )
            session.add(grant)
            session.add(AuditLog(
                request_id=str(uuid4()), action="agent.oauth.granted",
                target_type="agent_oauth_grant", target_id=grant.grant_id,
                changes={"clientId": client_id}, actor_id=grant.user_id,
                source_terminal="agent",
            ))
            return self._issue_pair(session, grant, now)

    def refresh(self, *, refresh_token: str, client_id: str, resource: str) -> dict[str, str | int]:
        self._client(client_id)
        self._resource(resource)
        now = self._now()
        with self._sessions() as session, session.begin():
            token = session.scalar(select(AgentOAuthToken).where(
                AgentOAuthToken.token_digest == self._digest(refresh_token)
            ))
            if token is None or token.kind != "refresh":
                raise OAuthInvalid("invalid_grant")
            grant = session.get(AgentOAuthGrant, token.grant_id)
            if grant is None or grant.client_id != client_id or grant.resource != resource:
                raise OAuthInvalid("invalid_grant")
            shared = self._active_shared(
                session, grant.shared_auth_id, grant.user_id, now, lock=True
            )
            token = session.scalar(
                select(AgentOAuthToken)
                .where(AgentOAuthToken.token_id == token.token_id)
                .with_for_update()
            )
            if token is None or token.revoked_at is not None:
                raise OAuthInvalid("invalid_grant")
            if token.consumed_at is not None:
                shared.revoked_at = now
                session.add(AuditLog(
                    request_id=str(uuid4()), action="agent.oauth.refresh_replay",
                    target_type="admin_shared_authorization", target_id=shared.auth_id,
                    changes={"result": "revoked"}, actor_id=grant.user_id,
                    source_terminal="agent",
                ))
                return {"error": "invalid_grant"}
            token.consumed_at = now
            return self._issue_pair(session, grant, now)

    def verify_access(self, raw_token: str) -> tuple[str, str, str, datetime] | None:
        now = self._now()
        with self._sessions() as session:
            token = session.scalar(select(AgentOAuthToken).where(
                AgentOAuthToken.token_digest == self._digest(raw_token),
                AgentOAuthToken.kind == "access",
            ))
            if (
                token is None or token.revoked_at is not None or token.consumed_at is not None
                or token.expires_at is None or token.expires_at <= now
            ):
                return None
            grant = session.get(AgentOAuthGrant, token.grant_id)
            if (
                grant is None
                or grant.client_id != self.client_id
                or grant.resource != self.resource
            ):
                return None
            try:
                self._active_shared(session, grant.shared_auth_id, grant.user_id, now)
            except OAuthInvalid:
                return None
            return grant.user_id, grant.shared_auth_id, grant.client_id, token.expires_at

    def revoke(self, *, raw_token: str, client_id: str) -> None:
        self._client(client_id)
        now = self._now()
        with self._sessions() as session, session.begin():
            token = session.scalar(select(AgentOAuthToken).where(
                AgentOAuthToken.token_digest == self._digest(raw_token)
            ))
            if token is None:
                return
            grant = session.get(AgentOAuthGrant, token.grant_id)
            if grant is None or grant.client_id != client_id:
                return
            shared = session.scalar(select(AdminSharedAuthorization).where(
                AdminSharedAuthorization.auth_id == grant.shared_auth_id
            ).with_for_update())
            if shared is None or shared.revoked_at is not None:
                return
            shared.revoked_at = now
            session.add(AuditLog(
                request_id=str(uuid4()), action="agent.oauth.revoked",
                target_type="admin_shared_authorization", target_id=shared.auth_id,
                changes={"result": "revoked"}, actor_id=grant.user_id,
                source_terminal="agent",
            ))

    def record_tool_success(
        self, *, auth_id: str, user_id: str, tool: str, request_id: str
    ) -> None:
        now = self._now()
        with self._sessions() as session, session.begin():
            shared = self._active_shared(session, auth_id, user_id, now, lock=True)
            shared.last_activity_at = now
            session.add(AuditLog(
                request_id=request_id, action=f"agent.tool.{tool}",
                target_type="user", target_id=user_id, changes={"tool": tool},
                actor_id=user_id, source_terminal="agent",
            ))
