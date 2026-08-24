import hashlib
import hmac
import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.avatar import AvatarStore
from app.adapters.identity import FeishuIdentity, FeishuProfile
from app.adapters.sms import SmsSender
from app.adapters.wechat import WechatIdentity
from app.db.models import (
    AdminApplication,
    AuditLog,
    ExternalIdentity,
    FactoryApplication,
    MiniLoginAttempt,
    OAuthState,
    SmsChallenge,
    StoredFile,
    User,
    UserSession,
)
from app.modules.identity_access.security import PhoneProtector


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@dataclass(frozen=True)
class UserSnapshot:
    user_id: str
    role: str | None
    is_super_admin: bool
    is_enabled: bool
    display_name: str
    feishu_avatar_url: str | None
    mini_avatar_external_url: str | None
    mini_avatar_file_id: int | None
    phone_masked: str | None
    factory_id: str | None
    factory_position: str | None
    version: int


@dataclass(frozen=True)
class FeishuLoginStart:
    authorization_url: str
    state: str


@dataclass(frozen=True)
class WebLoginResult:
    user: UserSnapshot
    web_session_token: str
    refresh_token: str
    csrf_token: str
    redirect_to: str


class IdentityAccessError(ValueError):
    pass


class OAuthStateInvalid(IdentityAccessError):
    pass


class ApplicationConflict(IdentityAccessError):
    pass


class VerificationInvalid(IdentityAccessError):
    pass


class SmsRateLimited(IdentityAccessError):
    pass


class PermissionDenied(IdentityAccessError):
    pass


class SessionInvalid(IdentityAccessError):
    pass


class AvatarInvalid(IdentityAccessError):
    pass


class ResourceNotFound(IdentityAccessError):
    pass


@dataclass(frozen=True)
class SmsChallengeSnapshot:
    challenge_id: str
    phone_masked: str
    expires_at: datetime


@dataclass(frozen=True)
class AdminApplicationSnapshot:
    application_id: str
    user_id: str
    display_name: str
    phone_masked: str
    status: str
    rejection_reason: str | None
    submitted_at: datetime
    reviewed_at: datetime | None
    reviewed_by: str | None
    version: int


@dataclass(frozen=True)
class SessionTokens:
    access_token: str
    refresh_token: str | None
    csrf_token: str | None
    expires_at: datetime


@dataclass(frozen=True)
class MiniLoginResult:
    status: str
    binding_token: str | None = None
    user: UserSnapshot | None = None
    session: SessionTokens | None = None
    rejection_reason: str | None = None


@dataclass(frozen=True)
class AvatarSnapshot:
    file_id: int
    mime_type: str
    size_bytes: int


@dataclass(frozen=True)
class AvatarContent:
    content: bytes
    mime_type: str


class IdentityAccessService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        feishu_identity: FeishuIdentity | None = None,
        sms_sender: SmsSender | None = None,
        wechat_identity: WechatIdentity | None = None,
        avatar_store: AvatarStore | None = None,
        token_secret: bytes | None = None,
        phone_encryption_secret: bytes | None = None,
        phone_digest_secret: bytes | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        verification_code_factory: Callable[[], str] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._feishu_identity = feishu_identity
        self._sms_sender = sms_sender
        self._wechat_identity = wechat_identity
        self._avatar_store = avatar_store
        self._token_secret = token_secret or secrets.token_bytes(32)
        self._phone = PhoneProtector(
            encryption_secret=phone_encryption_secret or secrets.token_bytes(32),
            digest_secret=phone_digest_secret or secrets.token_bytes(32),
        )
        self._clock = clock
        self._verification_code_factory = verification_code_factory

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is not None:
            value = value.astimezone(UTC).replace(tzinfo=None)
        return value

    def _digest(self, raw_value: str) -> str:
        return hmac.new(self._token_secret, raw_value.encode(), hashlib.sha256).hexdigest()

    def start_feishu_login(self, *, return_to: str, request_id: str) -> FeishuLoginStart:
        del request_id
        if self._feishu_identity is None:
            raise RuntimeError("FeishuIdentity adapter is not configured")
        if not return_to.startswith("/") or return_to.startswith("//"):
            return_to = "/"
        raw_state = secrets.token_urlsafe(32)
        now = self._now()
        with self._session_factory() as session, session.begin():
            session.add(
                OAuthState(
                    state_digest=self._digest(raw_state),
                    terminal="web",
                    return_to=return_to,
                    expires_at=now + timedelta(minutes=10),
                )
            )
        return FeishuLoginStart(
            authorization_url=self._feishu_identity.authorization_url(state=raw_state),
            state=raw_state,
        )

    def complete_feishu_login(
        self,
        *,
        state: str,
        code: str,
        request_id: str,
    ) -> WebLoginResult:
        if self._feishu_identity is None:
            raise RuntimeError("FeishuIdentity adapter is not configured")
        now = self._now()
        with self._session_factory() as session, session.begin():
            oauth_state = session.scalar(
                select(OAuthState)
                .where(OAuthState.state_digest == self._digest(state))
                .with_for_update()
            )
            if (
                oauth_state is None
                or oauth_state.used_at is not None
                or oauth_state.expires_at <= now
            ):
                raise OAuthStateInvalid("oauth state is invalid")
            oauth_state.used_at = now
            return_to = oauth_state.return_to

        profile = self._feishu_identity.exchange_code(code=code)
        user = self.resolve_feishu_identity(
            scope=self._feishu_identity.scope,
            profile=profile,
            request_id=request_id,
        )
        session_token = secrets.token_urlsafe(32)
        refresh_token = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(32)
        with self._session_factory() as session, session.begin():
            session.add(
                UserSession(
                    session_id=str(uuid4()),
                    user_id=user.user_id,
                    terminal="web",
                    token_digest=self._digest(session_token),
                    refresh_token_digest=self._digest(refresh_token),
                    csrf_digest=self._digest(csrf_token),
                    expires_at=now + timedelta(hours=12),
                    refresh_expires_at=now + timedelta(days=30),
                    last_activity_at=now,
                )
            )
        return WebLoginResult(
            user=user,
            web_session_token=session_token,
            refresh_token=refresh_token,
            csrf_token=csrf_token,
            redirect_to=return_to,
        )

    def send_admin_application_code(
        self,
        *,
        user_id: str,
        phone: str,
        request_id: str,
    ) -> SmsChallengeSnapshot:
        if self._sms_sender is None:
            raise RuntimeError("SmsSender adapter is not configured")
        if re.fullmatch(r"1\d{10}", phone) is None:
            raise VerificationInvalid("phone is invalid")
        now = self._now()
        phone_digest = self._phone.digest(phone)
        code = (
            self._verification_code_factory()
            if self._verification_code_factory is not None
            else f"{secrets.randbelow(1_000_000):06d}"
        )
        if re.fullmatch(r"\d{6}", code) is None:
            raise RuntimeError("verification code factory returned an invalid code")
        challenge_id = str(uuid4())
        with self._session_factory() as session, session.begin():
            user = session.get(User, user_id)
            if user is None:
                raise VerificationInvalid("user is unavailable")
            latest = session.scalar(
                select(SmsChallenge)
                .where(
                    SmsChallenge.user_id == user_id,
                    SmsChallenge.purpose == "admin_application",
                    SmsChallenge.send_status == "sent",
                )
                .order_by(SmsChallenge.created_at.desc())
                .limit(1)
            )
            if latest is not None and latest.created_at > now - timedelta(seconds=60):
                raise SmsRateLimited("verification code was sent too recently")
            active = session.scalars(
                select(SmsChallenge).where(
                    SmsChallenge.user_id == user_id,
                    SmsChallenge.purpose == "admin_application",
                    SmsChallenge.verified_at.is_(None),
                    SmsChallenge.invalidated_at.is_(None),
                )
            ).all()
            for previous in active:
                previous.invalidated_at = now
            challenge = SmsChallenge(
                challenge_id=challenge_id,
                user_id=user_id,
                phone_encrypted=self._phone.encrypt(phone),
                phone_digest=phone_digest,
                phone_masked=self._phone.mask(phone),
                purpose="admin_application",
                code_digest=self._digest(f"{challenge_id}:{code}"),
                expires_at=now + timedelta(minutes=5),
                send_status="pending",
                request_id=request_id,
                created_at=now,
            )
            session.add(challenge)

        try:
            self._sms_sender.send_code(phone=phone, code=code)
        except Exception:
            with self._session_factory() as session, session.begin():
                failed = session.get(SmsChallenge, challenge_id)
                if failed is not None:
                    failed.send_status = "failed"
                    failed.failure_reason = "sms_unavailable"
                    failed.invalidated_at = now
            raise

        with self._session_factory() as session, session.begin():
            sent = session.get(SmsChallenge, challenge_id)
            if sent is None:
                raise RuntimeError("SMS challenge disappeared")
            sent.send_status = "sent"
        return SmsChallengeSnapshot(
            challenge_id=challenge_id,
            phone_masked=self._phone.mask(phone),
            expires_at=now + timedelta(minutes=5),
        )

    def submit_admin_application(
        self,
        *,
        user_id: str,
        request_id: str,
        challenge_id: str | None = None,
        verification_code: str | None = None,
    ) -> AdminApplicationSnapshot:
        now = self._now()
        if challenge_id is None and verification_code is None:
            with self._session_factory() as session, session.begin():
                pending = session.scalar(
                    select(AdminApplication).where(
                        AdminApplication.pending_user_id == user_id
                    )
                )
                if pending is not None:
                    raise ApplicationConflict("an application is already pending")
                user = session.get(User, user_id)
                if user is None or user.role is not None:
                    raise ApplicationConflict(
                        "user cannot submit an administrator application"
                    )
                if not all(
                    (user.phone_encrypted, user.phone_digest, user.phone_masked)
                ):
                    raise VerificationInvalid("verified Feishu phone is unavailable")
                previous = session.scalar(
                    select(AdminApplication)
                    .where(AdminApplication.user_id == user_id)
                    .order_by(AdminApplication.submitted_at.desc())
                    .limit(1)
                )
                application = AdminApplication(
                    application_id=str(uuid4()),
                    user_id=user_id,
                    pending_user_id=user_id,
                    feishu_display_name_snapshot=user.feishu_display_name,
                    feishu_avatar_url_snapshot=user.feishu_avatar_url,
                    phone_encrypted=user.phone_encrypted,
                    phone_digest=user.phone_digest,
                    phone_masked=user.phone_masked,
                    status="pending",
                    submitted_at=now,
                    version=1,
                    previous_application_id=(
                        previous.application_id if previous else None
                    ),
                )
                session.add(application)
                session.add(
                    AuditLog(
                        request_id=request_id,
                        action=(
                            "admin_application.resubmitted"
                            if previous
                            else "admin_application.submitted"
                        ),
                        target_type="admin_application",
                        target_id=application.application_id,
                        changes={
                            "status": "pending",
                            "phone": user.phone_masked,
                            "phoneSource": "feishu",
                        },
                        actor_id=user_id,
                        source_terminal="web",
                    )
                )
                return self._application_snapshot(application)
        if challenge_id is None or verification_code is None:
            raise VerificationInvalid("verification challenge is incomplete")
        verification_error: str | None = None
        result: AdminApplicationSnapshot | None = None
        with self._session_factory() as session, session.begin():
            pending = session.scalar(
                select(AdminApplication).where(AdminApplication.pending_user_id == user_id)
            )
            if pending is not None:
                raise ApplicationConflict("an application is already pending")
            challenge = session.scalar(
                select(SmsChallenge)
                .where(
                    SmsChallenge.challenge_id == challenge_id,
                    SmsChallenge.user_id == user_id,
                )
                .with_for_update()
            )
            if (
                challenge is None
                or challenge.send_status != "sent"
                or challenge.verified_at is not None
                or challenge.invalidated_at is not None
                or challenge.expires_at <= now
            ):
                raise VerificationInvalid("verification challenge is invalid")
            if challenge.attempts >= 5:
                challenge.invalidated_at = now
                verification_error = "verification attempts exceeded"
            elif not hmac.compare_digest(
                challenge.code_digest,
                self._digest(f"{challenge_id}:{verification_code}"),
            ):
                challenge.attempts += 1
                if challenge.attempts >= 5:
                    challenge.invalidated_at = now
                verification_error = "verification code is invalid"
            else:
                challenge.verified_at = now
                user = session.get(User, user_id)
                if user is None or user.role is not None:
                    raise ApplicationConflict(
                        "user cannot submit an administrator application"
                    )
                previous = session.scalar(
                    select(AdminApplication)
                    .where(AdminApplication.user_id == user_id)
                    .order_by(AdminApplication.submitted_at.desc())
                    .limit(1)
                )
                phone_encrypted = challenge.phone_encrypted
                phone_masked = challenge.phone_masked
                application = AdminApplication(
                    application_id=str(uuid4()),
                    user_id=user_id,
                    pending_user_id=user_id,
                    feishu_display_name_snapshot=user.feishu_display_name,
                    feishu_avatar_url_snapshot=user.feishu_avatar_url,
                    phone_encrypted=phone_encrypted,
                    phone_digest=challenge.phone_digest,
                    phone_masked=phone_masked,
                    status="pending",
                    submitted_at=now,
                    version=1,
                    previous_application_id=previous.application_id if previous else None,
                )
                user.phone_encrypted = phone_encrypted
                user.phone_digest = challenge.phone_digest
                user.phone_masked = phone_masked
                session.add(application)
                session.add(
                    AuditLog(
                        request_id=request_id,
                        action=(
                            "admin_application.resubmitted"
                            if previous
                            else "admin_application.submitted"
                        ),
                        target_type="admin_application",
                        target_id=application.application_id,
                        changes={"status": "pending", "phone": phone_masked},
                        actor_id=user_id,
                        source_terminal="web",
                    )
                )
                result = self._application_snapshot(application)
        if verification_error is not None:
            raise VerificationInvalid(verification_error)
        if result is None:
            raise RuntimeError("administrator application was not created")
        return result

    @staticmethod
    def _application_snapshot(application: AdminApplication) -> AdminApplicationSnapshot:
        return AdminApplicationSnapshot(
            application_id=application.application_id,
            user_id=application.user_id,
            display_name=application.feishu_display_name_snapshot,
            phone_masked=application.phone_masked,
            status=application.status,
            rejection_reason=application.rejection_reason,
            submitted_at=application.submitted_at,
            reviewed_at=application.reviewed_at,
            reviewed_by=application.reviewed_by,
            version=application.version,
        )

    def resolve_feishu_identity(
        self,
        *,
        scope: str,
        profile: FeishuProfile,
        request_id: str,
    ) -> UserSnapshot:
        now = self._now()
        phone = profile.phone
        if phone is not None and re.fullmatch(r"1\d{10}", phone) is None:
            raise VerificationInvalid("Feishu phone is invalid")
        with self._session_factory() as session, session.begin():
            identity = session.scalar(
                select(ExternalIdentity).where(
                    ExternalIdentity.platform == "feishu",
                    ExternalIdentity.scope == scope,
                    ExternalIdentity.platform_subject == profile.subject,
                )
            )
            if identity is None:
                if phone is not None:
                    duplicate = session.scalar(
                        select(User).where(User.phone_digest == self._phone.digest(phone))
                    )
                    if duplicate is not None:
                        raise ApplicationConflict(
                            "Feishu phone is already bound to another user"
                        )
                user = User(
                    user_id=str(uuid4()),
                    feishu_display_name=profile.display_name,
                    feishu_avatar_url=profile.avatar_url,
                    phone_encrypted=self._phone.encrypt(phone) if phone else None,
                    phone_digest=self._phone.digest(phone) if phone else None,
                    phone_masked=self._phone.mask(phone) if phone else None,
                )
                session.add(user)
                session.flush()
                identity = ExternalIdentity(
                    platform="feishu",
                    scope=scope,
                    platform_subject=profile.subject,
                    user_id=user.user_id,
                    bound_at=now,
                    last_login_at=now,
                )
                session.add(identity)
                session.add(
                    AuditLog(
                        request_id=request_id,
                        action="identity.feishu.created",
                        target_type="user",
                        target_id=user.user_id,
                        changes={"platform": "feishu", "scope": scope},
                        actor_id=user.user_id,
                        source_terminal="web",
                    )
                )
            else:
                existing_user = session.get(User, identity.user_id)
                if existing_user is None:
                    raise RuntimeError("external identity references a missing user")
                user = existing_user
                identity.last_login_at = now
                user.feishu_display_name = profile.display_name
                user.feishu_avatar_url = profile.avatar_url
                if phone is not None:
                    phone_digest = self._phone.digest(phone)
                    duplicate = session.scalar(
                        select(User).where(
                            User.phone_digest == phone_digest,
                            User.user_id != user.user_id,
                        )
                    )
                    if duplicate is not None:
                        raise ApplicationConflict(
                            "Feishu phone is already bound to another user"
                        )
                    user.phone_encrypted = self._phone.encrypt(phone)
                    user.phone_digest = phone_digest
                    user.phone_masked = self._phone.mask(phone)

            return self._user_snapshot(user)

    def get_user(self, *, user_id: str) -> UserSnapshot:
        with self._session_factory() as session:
            user = session.get(User, user_id)
            if user is None:
                raise KeyError(user_id)
            return self._user_snapshot(user)

    def bootstrap_super_admin(
        self,
        *,
        scope: str,
        profile: FeishuProfile,
        operator_source: str,
        request_id: str,
    ) -> UserSnapshot:
        snapshot = self.resolve_feishu_identity(
            scope=scope,
            profile=profile,
            request_id=request_id,
        )
        with self._session_factory() as session, session.begin():
            user = session.get(User, snapshot.user_id)
            if user is None:
                raise RuntimeError("super administrator target disappeared")
            changed = user.role != "admin" or not user.is_super_admin or not user.is_enabled
            user.role = "admin"
            user.is_super_admin = True
            user.is_enabled = True
            if changed:
                user.version += 1
            session.add(
                AuditLog(
                    request_id=request_id,
                    action="admin.super_initialized",
                    target_type="user",
                    target_id=user.user_id,
                    changes={
                        "result": "updated" if changed else "already_configured",
                        "operatorSource": operator_source,
                    },
                    actor_id=None,
                    source_terminal="command",
                )
            )
            return self._user_snapshot(user)

    def list_admin_applications(
        self,
        *,
        actor_id: str,
        status: str | None = None,
    ) -> list[AdminApplicationSnapshot]:
        with self._session_factory() as session:
            self._require_super_admin(session, actor_id)
            statement = select(AdminApplication)
            if status is not None:
                statement = statement.where(AdminApplication.status == status)
            applications = session.scalars(
                statement.order_by(AdminApplication.submitted_at.desc())
            ).all()
            return [self._application_snapshot(application) for application in applications]

    def get_admin_application(
        self,
        *,
        actor_id: str,
        application_id: str,
    ) -> AdminApplicationSnapshot:
        with self._session_factory() as session:
            self._require_super_admin(session, actor_id)
            application = session.get(AdminApplication, application_id)
            if application is None:
                raise ResourceNotFound("administrator application was not found")
            return self._application_snapshot(application)

    def list_admin_users(self, *, actor_id: str) -> list[UserSnapshot]:
        with self._session_factory() as session:
            self._require_super_admin(session, actor_id)
            users = session.scalars(
                select(User)
                .where(User.role == "admin")
                .order_by(User.is_super_admin.desc(), User.feishu_display_name, User.user_id)
            ).all()
            return [self._user_snapshot(user) for user in users]

    def approve_admin_application(
        self,
        *,
        actor_id: str,
        application_id: str,
        expected_version: int,
        request_id: str,
    ) -> AdminApplicationSnapshot:
        now = self._now()
        with self._session_factory() as session, session.begin():
            self._require_super_admin(session, actor_id)
            application = session.scalar(
                select(AdminApplication)
                .where(AdminApplication.application_id == application_id)
                .with_for_update()
            )
            if (
                application is None
                or application.status != "pending"
                or application.version != expected_version
            ):
                raise ApplicationConflict("administrator application was already processed")
            user = session.get(User, application.user_id)
            if user is None:
                raise RuntimeError("administrator application user disappeared")
            application.status = "approved"
            application.pending_user_id = None
            application.reviewed_by = actor_id
            application.reviewed_at = now
            application.version += 1
            user.role = "admin"
            user.is_super_admin = False
            user.is_enabled = True
            user.version += 1
            session.add(
                AuditLog(
                    request_id=request_id,
                    action="admin_application.approved",
                    target_type="admin_application",
                    target_id=application.application_id,
                    changes={"before": "pending", "after": "approved"},
                    actor_id=actor_id,
                    source_terminal="web",
                )
            )
            return self._application_snapshot(application)

    def reject_admin_application(
        self,
        *,
        actor_id: str,
        application_id: str,
        expected_version: int,
        reason: str,
        request_id: str,
    ) -> AdminApplicationSnapshot:
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise VerificationInvalid("rejection reason is required")
        now = self._now()
        with self._session_factory() as session, session.begin():
            self._require_super_admin(session, actor_id)
            application = session.scalar(
                select(AdminApplication)
                .where(AdminApplication.application_id == application_id)
                .with_for_update()
            )
            if (
                application is None
                or application.status != "pending"
                or application.version != expected_version
            ):
                raise ApplicationConflict("administrator application was already processed")
            application.status = "rejected"
            application.pending_user_id = None
            application.reviewed_by = actor_id
            application.reviewed_at = now
            application.rejection_reason = normalized_reason
            application.version += 1
            session.add(
                AuditLog(
                    request_id=request_id,
                    action="admin_application.rejected",
                    target_type="admin_application",
                    target_id=application.application_id,
                    changes={"before": "pending", "after": "rejected"},
                    actor_id=actor_id,
                    source_terminal="web",
                )
            )
            return self._application_snapshot(application)

    def issue_session(self, *, user_id: str, terminal: str) -> SessionTokens:
        if terminal not in {"web", "mini"}:
            raise ValueError("unsupported terminal")
        now = self._now()
        access_token = secrets.token_urlsafe(32)
        refresh_token = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(32) if terminal == "web" else None
        expires_at = now + (timedelta(minutes=15) if terminal == "mini" else timedelta(hours=12))
        with self._session_factory() as session, session.begin():
            user = session.get(User, user_id)
            if user is None or not user.is_enabled:
                raise SessionInvalid("user is unavailable")
            if terminal == "mini" and user.role == "factory" and user.factory_id is None:
                raise SessionInvalid("factory user affiliation is unavailable")
            session.add(
                UserSession(
                    session_id=str(uuid4()),
                    user_id=user_id,
                    terminal=terminal,
                    token_digest=self._digest(access_token),
                    refresh_token_digest=self._digest(refresh_token),
                    csrf_digest=self._digest(csrf_token) if csrf_token is not None else None,
                    expires_at=expires_at,
                    refresh_expires_at=now + timedelta(days=30),
                    last_activity_at=now,
                )
            )
        return SessionTokens(
            access_token=access_token,
            refresh_token=refresh_token,
            csrf_token=csrf_token,
            expires_at=expires_at,
        )

    def authenticate_session(
        self,
        *,
        token: str,
        terminal: str,
        csrf_token: str | None = None,
        require_csrf: bool = False,
    ) -> UserSnapshot:
        now = self._now()
        with self._session_factory() as session, session.begin():
            active_session = session.scalar(
                select(UserSession).where(
                    UserSession.token_digest == self._digest(token),
                    UserSession.terminal == terminal,
                )
            )
            if (
                active_session is None
                or active_session.revoked_at is not None
                or active_session.expires_at <= now
            ):
                raise SessionInvalid("session is invalid")
            if require_csrf and (
                terminal != "web"
                or csrf_token is None
                or active_session.csrf_digest is None
                or not hmac.compare_digest(
                    active_session.csrf_digest,
                    self._digest(csrf_token),
                )
            ):
                raise PermissionDenied("CSRF validation failed")
            user = session.get(User, active_session.user_id)
            if user is None or not user.is_enabled:
                raise SessionInvalid("session user is unavailable")
            if terminal == "mini" and user.role == "factory" and user.factory_id is None:
                raise SessionInvalid("session user is unavailable")
            active_session.last_activity_at = now
            return self._user_snapshot(user)

    def get_my_application(self, *, user_id: str) -> AdminApplicationSnapshot | None:
        with self._session_factory() as session:
            application = session.scalar(
                select(AdminApplication)
                .where(AdminApplication.user_id == user_id)
                .order_by(AdminApplication.submitted_at.desc())
                .limit(1)
            )
            return self._application_snapshot(application) if application is not None else None

    def refresh_mini_session(self, *, refresh_token: str) -> SessionTokens:
        now = self._now()
        new_access = secrets.token_urlsafe(32)
        new_refresh = secrets.token_urlsafe(32)
        expires_at = now + timedelta(minutes=15)
        with self._session_factory() as session, session.begin():
            active_session = session.scalar(
                select(UserSession)
                .where(
                    UserSession.refresh_token_digest == self._digest(refresh_token),
                    UserSession.terminal == "mini",
                )
                .with_for_update()
            )
            if (
                active_session is None
                or active_session.revoked_at is not None
                or active_session.refresh_expires_at is None
                or active_session.refresh_expires_at <= now
            ):
                raise SessionInvalid("refresh token is invalid")
            user = session.get(User, active_session.user_id)
            if user is None or not user.is_enabled:
                raise SessionInvalid("refresh token user is unavailable")
            if user.role == "factory" and user.factory_id is None:
                raise SessionInvalid("refresh token user is unavailable")
            active_session.token_digest = self._digest(new_access)
            active_session.refresh_token_digest = self._digest(new_refresh)
            active_session.expires_at = expires_at
            active_session.refresh_expires_at = now + timedelta(days=30)
            active_session.last_activity_at = now
        return SessionTokens(
            access_token=new_access,
            refresh_token=new_refresh,
            csrf_token=None,
            expires_at=expires_at,
        )

    def refresh_web_session(self, *, refresh_token: str) -> SessionTokens:
        now = self._now()
        new_access = secrets.token_urlsafe(32)
        new_refresh = secrets.token_urlsafe(32)
        new_csrf = secrets.token_urlsafe(32)
        expires_at = now + timedelta(hours=12)
        with self._session_factory() as session, session.begin():
            active_session = session.scalar(
                select(UserSession)
                .where(
                    UserSession.refresh_token_digest == self._digest(refresh_token),
                    UserSession.terminal == "web",
                )
                .with_for_update()
            )
            if (
                active_session is None
                or active_session.revoked_at is not None
                or active_session.refresh_expires_at is None
                or active_session.refresh_expires_at <= now
            ):
                raise SessionInvalid("refresh token is invalid")
            user = session.get(User, active_session.user_id)
            if user is None or not user.is_enabled or user.role == "factory":
                raise SessionInvalid("refresh token user is unavailable")
            active_session.token_digest = self._digest(new_access)
            active_session.refresh_token_digest = self._digest(new_refresh)
            active_session.csrf_digest = self._digest(new_csrf)
            active_session.expires_at = expires_at
            active_session.refresh_expires_at = now + timedelta(days=30)
            active_session.last_activity_at = now
        return SessionTokens(
            access_token=new_access,
            refresh_token=new_refresh,
            csrf_token=new_csrf,
            expires_at=expires_at,
        )

    def logout_session(self, *, token: str, terminal: str, request_id: str) -> None:
        now = self._now()
        with self._session_factory() as session, session.begin():
            active_session = session.scalar(
                select(UserSession)
                .where(
                    UserSession.token_digest == self._digest(token),
                    UserSession.terminal == terminal,
                )
                .with_for_update()
            )
            if active_session is None or active_session.revoked_at is not None:
                return
            active_session.revoked_at = now
            session.add(
                AuditLog(
                    request_id=request_id,
                    action=f"session.{terminal}.logout",
                    target_type="user_session",
                    target_id=active_session.session_id,
                    changes={"terminal": terminal, "result": "revoked"},
                    actor_id=active_session.user_id,
                    source_terminal=terminal,
                )
            )

    def set_admin_enabled(
        self,
        *,
        actor_id: str,
        target_user_id: str,
        enabled: bool,
        expected_version: int,
        request_id: str,
    ) -> UserSnapshot:
        now = self._now()
        with self._session_factory() as session, session.begin():
            self._require_super_admin(session, actor_id)
            target = session.scalar(
                select(User).where(User.user_id == target_user_id).with_for_update()
            )
            if target is None or target.role != "admin":
                raise ResourceNotFound("administrator was not found")
            if target.is_super_admin:
                raise PermissionDenied("super administrators cannot be disabled")
            if target.version != expected_version:
                raise ApplicationConflict("administrator version conflict")
            before = target.is_enabled
            target.is_enabled = enabled
            target.version += 1
            if not enabled:
                session.execute(
                    update(UserSession)
                    .where(
                        UserSession.user_id == target_user_id,
                        UserSession.revoked_at.is_(None),
                    )
                    .values(revoked_at=now)
                )
            session.add(
                AuditLog(
                    request_id=request_id,
                    action="admin.enabled" if enabled else "admin.disabled",
                    target_type="user",
                    target_id=target.user_id,
                    changes={"before": before, "after": enabled},
                    actor_id=actor_id,
                    source_terminal="web",
                )
            )
            return self._user_snapshot(target)

    def begin_wechat_login(self, *, login_code: str, request_id: str) -> MiniLoginResult:
        del request_id
        if self._wechat_identity is None:
            raise RuntimeError("WechatIdentity adapter is not configured")
        profile = self._wechat_identity.exchange_login_code(code=login_code)
        scope = self._wechat_identity.scope
        with self._session_factory() as session:
            identity = session.scalar(
                select(ExternalIdentity).where(
                    ExternalIdentity.platform == "wechat",
                    ExternalIdentity.scope == scope,
                    ExternalIdentity.platform_subject == profile.subject,
                )
            )
            if identity is not None:
                user = session.get(User, identity.user_id)
                if user is None:
                    return MiniLoginResult(status="disabled")
                snapshot = self._user_snapshot(user)
                if not user.is_enabled:
                    return MiniLoginResult(status="disabled", user=snapshot)
                identity_id = identity.id
                if user.role in {"admin", "factory"}:
                    status = "authenticated"
                    rejection_reason = None
                else:
                    application = session.scalar(
                        select(FactoryApplication)
                        .where(FactoryApplication.user_id == user.user_id)
                        .order_by(FactoryApplication.submitted_at.desc())
                        .limit(1)
                    )
                    status = (
                        application.status
                        if application is not None
                        else "factory_application_required"
                    )
                    rejection_reason = (
                        application.rejection_reason if application is not None else None
                    )
            else:
                snapshot = None
                identity_id = None
                status = "phone_required"
                rejection_reason = None
        if snapshot is not None:
            with self._session_factory() as session, session.begin():
                identity = session.get(ExternalIdentity, identity_id)
                if identity is not None:
                    identity.last_login_at = self._now()
            return MiniLoginResult(
                status=status,
                user=snapshot,
                session=self.issue_session(user_id=snapshot.user_id, terminal="mini"),
                rejection_reason=rejection_reason,
            )

        raw_token = secrets.token_urlsafe(32)
        now = self._now()
        with self._session_factory() as session, session.begin():
            session.add(
                MiniLoginAttempt(
                    attempt_id=str(uuid4()),
                    token_digest=self._digest(raw_token),
                    scope=scope,
                    platform_subject=profile.subject,
                    wechat_avatar_url=profile.avatar_url,
                    expires_at=now + timedelta(minutes=10),
                )
            )
        return MiniLoginResult(status="phone_required", binding_token=raw_token)

    def bind_wechat_phone(
        self,
        *,
        binding_token: str,
        phone_code: str,
        request_id: str,
    ) -> MiniLoginResult:
        if self._wechat_identity is None:
            raise RuntimeError("WechatIdentity adapter is not configured")
        now = self._now()
        with self._session_factory() as session, session.begin():
            attempt = session.scalar(
                select(MiniLoginAttempt)
                .where(MiniLoginAttempt.token_digest == self._digest(binding_token))
                .with_for_update()
            )
            if (
                attempt is None
                or attempt.used_at is not None
                or attempt.expires_at <= now
                or attempt.scope != self._wechat_identity.scope
            ):
                raise SessionInvalid("mini-program binding attempt is invalid")
            attempt.used_at = now
            scope = attempt.scope
            platform_subject = attempt.platform_subject
            wechat_avatar_url = attempt.wechat_avatar_url

        phone = self._wechat_identity.exchange_phone_code(code=phone_code)
        phone_digest = self._phone.digest(phone)
        with self._session_factory() as session:
            matched_users = session.scalars(
                select(User).where(User.phone_digest == phone_digest)
            ).all()
            if len(matched_users) > 1:
                return MiniLoginResult(status="ambiguous")
            if not matched_users:
                user = None
                application = None
            else:
                user = matched_users[0]
                application = session.scalar(
                    select(AdminApplication)
                    .where(AdminApplication.user_id == user.user_id)
                    .order_by(AdminApplication.submitted_at.desc())
                    .limit(1)
                )

        if user is None:
            user_id = str(uuid4())
            with self._session_factory() as session, session.begin():
                created = User(
                    user_id=user_id,
                    feishu_display_name="微信用户",
                    mini_avatar_external_url=wechat_avatar_url,
                    phone_encrypted=self._phone.encrypt(phone),
                    phone_digest=phone_digest,
                    phone_masked=self._phone.mask(phone),
                )
                session.add(created)
                session.flush()
                session.add(
                    ExternalIdentity(
                        platform="wechat",
                        scope=scope,
                        platform_subject=platform_subject,
                        user_id=user_id,
                        bound_at=now,
                        last_login_at=now,
                    )
                )
                session.add(
                    AuditLog(
                        request_id=request_id,
                        action="identity.wechat.factory_applicant_created",
                        target_type="user",
                        target_id=user_id,
                        changes={"scope": scope, "phone": self._phone.mask(phone)},
                        actor_id=user_id,
                        source_terminal="mini",
                    )
                )
            snapshot = self.get_user(user_id=user_id)
            return MiniLoginResult(
                status="factory_application_required",
                user=snapshot,
                session=self.issue_session(user_id=user_id, terminal="mini"),
            )

        if application is not None:
            user = matched_users[0]
            if application.status == "pending":
                return MiniLoginResult(status="pending")
            if application.status == "rejected":
                return MiniLoginResult(
                    status="rejected",
                    rejection_reason=application.rejection_reason,
                )
            if user.role != "admin":
                return MiniLoginResult(status="unmatched")
            if not user.is_enabled:
                return MiniLoginResult(status="disabled")
            user_id = user.user_id
            final_status = "authenticated"
            final_reason = None
        elif user.role == "factory":
            if not user.is_enabled or user.factory_id is None:
                return MiniLoginResult(status="disabled")
            user_id = user.user_id
            final_status = "authenticated"
            final_reason = None
        elif user.role is None:
            with self._session_factory() as session:
                factory_application = session.scalar(
                    select(FactoryApplication)
                    .where(FactoryApplication.user_id == user.user_id)
                    .order_by(FactoryApplication.submitted_at.desc())
                    .limit(1)
                )
            user_id = user.user_id
            final_status = (
                factory_application.status
                if factory_application is not None
                else "factory_application_required"
            )
            final_reason = (
                factory_application.rejection_reason
                if factory_application is not None
                else None
            )
        elif user.role == "admin":
            user_id = user.user_id
            final_status = "authenticated"
            final_reason = None
        else:
            return MiniLoginResult(status="unmatched")

        with self._session_factory() as session, session.begin():
            existing = session.scalar(
                select(ExternalIdentity)
                .where(
                    ExternalIdentity.platform == "wechat",
                    ExternalIdentity.scope == scope,
                    ExternalIdentity.platform_subject == platform_subject,
                )
                .with_for_update()
            )
            if existing is not None and existing.user_id != user_id:
                session.add(
                    AuditLog(
                        request_id=request_id,
                        action="identity.wechat.conflict",
                        target_type="external_identity",
                        target_id=platform_subject,
                        changes={"scope": scope, "result": "conflict"},
                        actor_id=user_id,
                        source_terminal="mini",
                    )
                )
                return MiniLoginResult(status="ambiguous")
            if existing is None:
                session.add(
                    ExternalIdentity(
                        platform="wechat",
                        scope=scope,
                        platform_subject=platform_subject,
                        user_id=user_id,
                        bound_at=now,
                        last_login_at=now,
                    )
                )
            else:
                existing.last_login_at = now
            bound_user = session.get(User, user_id)
            if (
                bound_user is not None
                and bound_user.mini_avatar_file_id is None
                and wechat_avatar_url is not None
            ):
                bound_user.mini_avatar_external_url = wechat_avatar_url
            session.add(
                AuditLog(
                    request_id=request_id,
                    action="identity.wechat.bound",
                    target_type="user",
                    target_id=user_id,
                    changes={"scope": scope, "phone": self._phone.mask(phone)},
                    actor_id=user_id,
                    source_terminal="mini",
                )
            )
        snapshot = self.get_user(user_id=user_id)
        return MiniLoginResult(
            status=final_status,
            user=snapshot,
            session=self.issue_session(user_id=user_id, terminal="mini"),
            rejection_reason=final_reason,
        )

    def get_mini_avatar(self, *, user_id: str) -> AvatarContent:
        if self._avatar_store is None:
            raise RuntimeError("AvatarStore adapter is not configured")
        with self._session_factory() as session:
            user = session.get(User, user_id)
            if user is None or user.role != "admin" or not user.is_enabled:
                raise PermissionDenied("active administrator is required")
            stored = (
                session.get(StoredFile, user.mini_avatar_file_id)
                if user.mini_avatar_file_id is not None
                else None
            )
            if stored is None:
                raise ResourceNotFound("mini-program avatar was not found")
            content = self._avatar_store.get(object_key=stored.object_key)
            return AvatarContent(content=content, mime_type=stored.mime_type)

    def replace_mini_avatar(
        self,
        *,
        user_id: str,
        original_filename: str,
        mime_type: str,
        content: bytes,
        idempotency_key: str,
        request_id: str,
    ) -> AvatarSnapshot:
        if self._avatar_store is None:
            raise RuntimeError("AvatarStore adapter is not configured")
        if not idempotency_key or len(idempotency_key) > 191:
            raise AvatarInvalid("avatar idempotency key is invalid")
        if not content or len(content) > 5 * 1024 * 1024:
            raise AvatarInvalid("avatar size is invalid")
        if not self._is_valid_avatar(content=content, mime_type=mime_type):
            raise AvatarInvalid("avatar type is invalid")
        with self._session_factory() as session:
            existing = session.scalar(
                select(StoredFile).where(
                    StoredFile.uploaded_by == user_id,
                    StoredFile.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                return AvatarSnapshot(
                    file_id=existing.file_id,
                    mime_type=existing.mime_type,
                    size_bytes=existing.size_bytes,
                )

        extension = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}[mime_type]
        object_key = f"avatars/{uuid4().hex}.{extension}"
        self._avatar_store.put(
            object_key=object_key,
            content=content,
            content_type=mime_type,
        )
        now = self._now()
        old_object_key: str | None = None
        try:
            with self._session_factory() as session, session.begin():
                user = session.scalar(select(User).where(User.user_id == user_id).with_for_update())
                if user is None or user.role != "admin" or not user.is_enabled:
                    raise PermissionDenied("active administrator is required")
                old_file = (
                    session.get(StoredFile, user.mini_avatar_file_id)
                    if user.mini_avatar_file_id is not None
                    else None
                )
                stored = StoredFile(
                    bucket=self._avatar_store.bucket,
                    object_key=object_key,
                    original_filename=original_filename[:255],
                    mime_type=mime_type,
                    size_bytes=len(content),
                    content_sha256=hashlib.sha256(content).hexdigest(),
                    uploaded_by=user_id,
                    idempotency_key=idempotency_key,
                )
                session.add(stored)
                session.flush()
                user.mini_avatar_file_id = stored.file_id
                user.mini_avatar_external_url = None
                user.version += 1
                if old_file is not None:
                    old_file.replaced_at = now
                    old_object_key = old_file.object_key
                session.add(
                    AuditLog(
                        request_id=request_id,
                        action="profile.mini_avatar.replaced",
                        target_type="stored_file",
                        target_id=str(stored.file_id),
                        changes={"mimeType": mime_type, "sizeBytes": len(content)},
                        actor_id=user_id,
                        source_terminal="mini",
                    )
                )
                result = AvatarSnapshot(
                    file_id=stored.file_id,
                    mime_type=stored.mime_type,
                    size_bytes=stored.size_bytes,
                )
        except Exception:
            self._avatar_store.delete(object_key=object_key)
            raise
        if old_object_key is not None:
            self._avatar_store.delete(object_key=old_object_key)
        return result

    @staticmethod
    def _is_valid_avatar(*, content: bytes, mime_type: str) -> bool:
        if mime_type == "image/png":
            return content.startswith(b"\x89PNG\r\n\x1a\n")
        if mime_type == "image/jpeg":
            return content.startswith(b"\xff\xd8\xff")
        if mime_type == "image/webp":
            return len(content) >= 12 and content.startswith(b"RIFF") and content[8:12] == b"WEBP"
        return False

    @staticmethod
    def _require_super_admin(session: Session, actor_id: str) -> User:
        actor = session.get(User, actor_id)
        if (
            actor is None
            or actor.role != "admin"
            or not actor.is_super_admin
            or not actor.is_enabled
        ):
            raise PermissionDenied("super administrator permission is required")
        return actor

    @staticmethod
    def _user_snapshot(user: User) -> UserSnapshot:
        return UserSnapshot(
            user_id=user.user_id,
            role=user.role,
            is_super_admin=user.is_super_admin,
            is_enabled=user.is_enabled,
            display_name=user.feishu_display_name,
            feishu_avatar_url=user.feishu_avatar_url,
            mini_avatar_external_url=user.mini_avatar_external_url,
            mini_avatar_file_id=user.mini_avatar_file_id,
            phone_masked=user.phone_masked,
            factory_id=user.factory_id,
            factory_position=user.factory_position,
            version=user.version,
        )
