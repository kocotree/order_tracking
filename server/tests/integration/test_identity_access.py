from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.avatar import FakeAvatarStore
from app.adapters.identity import FakeFeishuIdentity
from app.adapters.sms import FakeSmsSender
from app.adapters.wechat import FakeWechatIdentity, WechatProfile
from app.modules.identity_access import (
    AdminApplicationSnapshot,
    ApplicationConflict,
    AvatarInvalid,
    FeishuProfile,
    IdentityAccessService,
    OAuthStateInvalid,
    PermissionDenied,
    SessionInvalid,
    VerificationInvalid,
)


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


def test_feishu_identity_is_reused_inside_scope_and_isolated_between_scopes(
    test_database_engine: Engine,
) -> None:
    clean_identity_tables(test_database_engine)
    service = IdentityAccessService(sessionmaker(test_database_engine, class_=Session))
    profile = FeishuProfile(
        subject="ou_same_external_subject",
        display_name="煎饼",
        avatar_url="https://example.invalid/avatar.png",
    )

    first = service.resolve_feishu_identity(
        scope="tenant-a/app-a",
        profile=profile,
        request_id="req-feishu-first",
    )
    repeated = service.resolve_feishu_identity(
        scope="tenant-a/app-a",
        profile=profile,
        request_id="req-feishu-repeat",
    )
    other_scope = service.resolve_feishu_identity(
        scope="tenant-b/app-a",
        profile=profile,
        request_id="req-feishu-other-scope",
    )

    assert repeated.user_id == first.user_id
    assert other_scope.user_id != first.user_id
    assert first.role is None
    assert first.display_name == "煎饼"


def test_oauth_state_is_short_lived_single_use_and_callback_creates_web_session(
    test_database_engine: Engine,
) -> None:
    clean_identity_tables(test_database_engine)
    now = datetime(2026, 8, 20, 8, 0, tzinfo=UTC)
    feishu = FakeFeishuIdentity(
        profiles={
            "valid-code": FeishuProfile(
                subject="ou_login_user",
                display_name="煎饼",
                avatar_url=None,
            )
        }
    )
    service = IdentityAccessService(
        sessionmaker(test_database_engine, class_=Session),
        feishu_identity=feishu,
        token_secret=b"test-token-secret-not-for-production",
        clock=lambda: now,
    )

    started = service.start_feishu_login(
        return_to="/admin-apply",
        request_id="req-oauth-start",
    )
    completed = service.complete_feishu_login(
        state=started.state,
        code="valid-code",
        request_id="req-oauth-callback",
    )

    assert started.authorization_url.endswith(started.state)
    assert completed.user.display_name == "煎饼"
    assert completed.web_session_token
    assert completed.csrf_token
    assert completed.redirect_to == "/admin-apply"

    with pytest.raises(OAuthStateInvalid):
        service.complete_feishu_login(
            state=started.state,
            code="valid-code",
            request_id="req-oauth-replay",
        )

    expired_service = IdentityAccessService(
        sessionmaker(test_database_engine, class_=Session),
        feishu_identity=feishu,
        token_secret=b"test-token-secret-not-for-production",
        clock=lambda: now + timedelta(minutes=11),
    )
    expired = service.start_feishu_login(return_to="/", request_id="req-oauth-expired")
    with pytest.raises(OAuthStateInvalid):
        expired_service.complete_feishu_login(
            state=expired.state,
            code="valid-code",
            request_id="req-oauth-expired-callback",
        )


def test_verified_sms_creates_one_pending_admin_application_without_plaintext(
    test_database_engine: Engine,
) -> None:
    clean_identity_tables(test_database_engine)
    sms = FakeSmsSender()
    factory = sessionmaker(test_database_engine, class_=Session)
    service = IdentityAccessService(
        factory,
        sms_sender=sms,
        token_secret=b"test-token-secret-not-for-production",
        phone_encryption_secret=b"test-phone-encryption-secret",
        phone_digest_secret=b"test-phone-digest-secret",
    )
    applicant = service.resolve_feishu_identity(
        scope="tenant-a/app-a",
        profile=FeishuProfile(subject="ou_applicant", display_name="煎饼"),
        request_id="req-create-applicant",
    )

    challenge = service.send_admin_application_code(
        user_id=applicant.user_id,
        phone="13812345122",
        request_id="req-send-sms",
    )
    application = service.submit_admin_application(
        user_id=applicant.user_id,
        challenge_id=challenge.challenge_id,
        verification_code=sms.last_code_for("13812345122"),
        request_id="req-submit-application",
    )

    assert application.status == "pending"
    assert application.phone_masked == "138****5122"
    assert application.display_name == "煎饼"
    with pytest.raises(ApplicationConflict):
        service.submit_admin_application(
            user_id=applicant.user_id,
            challenge_id=challenge.challenge_id,
            verification_code=sms.last_code_for("13812345122"),
            request_id="req-submit-duplicate",
        )

    with test_database_engine.connect() as connection:
        raw = " ".join(
            str(value)
            for value in connection.execute(
                text(
                    "SELECT phone_encrypted, phone_digest, phone_masked "
                    "FROM users WHERE user_id = :user_id"
                ),
                {"user_id": applicant.user_id},
            ).one()
        )
        code_digest = connection.execute(
            text("SELECT code_digest FROM sms_challenges WHERE challenge_id = :challenge_id"),
            {"challenge_id": challenge.challenge_id},
        ).scalar_one()
    assert "13812345122" not in raw
    assert sms.last_code_for("13812345122") not in code_digest


def test_wrong_sms_code_is_limited_and_persistently_invalidates_challenge(
    test_database_engine: Engine,
) -> None:
    clean_identity_tables(test_database_engine)
    sms = FakeSmsSender()
    service = IdentityAccessService(
        sessionmaker(test_database_engine, class_=Session),
        sms_sender=sms,
        token_secret=b"test-token-secret-not-for-production",
        phone_encryption_secret=b"test-phone-encryption-secret",
        phone_digest_secret=b"test-phone-digest-secret",
    )
    applicant = service.resolve_feishu_identity(
        scope="tenant-a/app-a",
        profile=FeishuProfile(subject="ou_wrong_code", display_name="煎饼"),
        request_id="req-create-wrong-code-user",
    )
    challenge = service.send_admin_application_code(
        user_id=applicant.user_id,
        phone="13812345122",
        request_id="req-send-wrong-code",
    )

    for attempt in range(5):
        with pytest.raises(VerificationInvalid):
            service.submit_admin_application(
                user_id=applicant.user_id,
                challenge_id=challenge.challenge_id,
                verification_code="000000",
                request_id=f"req-wrong-code-{attempt}",
            )

    with test_database_engine.connect() as connection:
        attempts, invalidated_at = connection.execute(
            text(
                "SELECT attempts, invalidated_at FROM sms_challenges "
                "WHERE challenge_id = :challenge_id"
            ),
            {"challenge_id": challenge.challenge_id},
        ).one()
    assert attempts == 5
    assert invalidated_at is not None
    with pytest.raises(VerificationInvalid):
        service.submit_admin_application(
            user_id=applicant.user_id,
            challenge_id=challenge.challenge_id,
            verification_code=sms.last_code_for("13812345122"),
            request_id="req-correct-code-after-lockout",
        )


def test_only_super_admin_can_review_and_approval_grants_ordinary_admin(
    test_database_engine: Engine,
) -> None:
    clean_identity_tables(test_database_engine)
    sms = FakeSmsSender()
    factory = sessionmaker(test_database_engine, class_=Session)
    service = IdentityAccessService(
        factory,
        sms_sender=sms,
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
        profile=FeishuProfile(subject="ou_candidate", display_name="煎饼"),
        request_id="req-create-candidate",
    )
    challenge = service.send_admin_application_code(
        user_id=applicant.user_id,
        phone="13812345122",
        request_id="req-send-candidate-code",
    )
    application = service.submit_admin_application(
        user_id=applicant.user_id,
        challenge_id=challenge.challenge_id,
        verification_code=sms.last_code_for("13812345122"),
        request_id="req-submit-candidate",
    )

    with pytest.raises(PermissionDenied):
        service.list_admin_applications(actor_id=applicant.user_id)

    barrier = Barrier(2)

    def approve_concurrently(request_id: str) -> str:
        barrier.wait()
        try:
            return service.approve_admin_application(
                actor_id=super_admin.user_id,
                application_id=application.application_id,
                expected_version=application.version,
                request_id=request_id,
            ).status
        except ApplicationConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(
            pool.map(
                approve_concurrently,
                ["req-approve-candidate-a", "req-approve-candidate-b"],
            )
        )

    assert sorted(outcomes) == ["approved", "conflict"]
    approved_user = service.get_user(user_id=applicant.user_id)
    assert approved_user.role == "admin"
    assert approved_user.is_super_admin is False
    with pytest.raises(ApplicationConflict):
        service.approve_admin_application(
            actor_id=super_admin.user_id,
            application_id=application.application_id,
            expected_version=application.version,
            request_id="req-approve-candidate-again",
        )

    # Idempotent controlled bootstrap may promote only the configured external identity.
    repeated_super = service.bootstrap_super_admin(
        scope="tenant-a/app-a",
        profile=FeishuProfile(subject="ou_super", display_name="松子"),
        operator_source="deployment-command",
        request_id="req-bootstrap-super-again",
    )
    assert repeated_super.user_id == super_admin.user_id


def test_rejection_requires_reason_and_reapplication_preserves_history(
    test_database_engine: Engine,
) -> None:
    clean_identity_tables(test_database_engine)
    now = [datetime(2026, 8, 20, 8, 0, tzinfo=UTC)]
    sms = FakeSmsSender()
    service = IdentityAccessService(
        sessionmaker(test_database_engine, class_=Session),
        sms_sender=sms,
        token_secret=b"test-token-secret-not-for-production",
        phone_encryption_secret=b"test-phone-encryption-secret",
        phone_digest_secret=b"test-phone-digest-secret",
        clock=lambda: now[0],
    )
    super_admin = service.bootstrap_super_admin(
        scope="tenant-a/app-a",
        profile=FeishuProfile(subject="ou_super", display_name="松子"),
        operator_source="deployment-command",
        request_id="req-bootstrap-super",
    )
    applicant = service.resolve_feishu_identity(
        scope="tenant-a/app-a",
        profile=FeishuProfile(subject="ou_reapply", display_name="煎饼"),
        request_id="req-create-reapply",
    )
    first_challenge = service.send_admin_application_code(
        user_id=applicant.user_id,
        phone="13812345122",
        request_id="req-first-code",
    )
    first = service.submit_admin_application(
        user_id=applicant.user_id,
        challenge_id=first_challenge.challenge_id,
        verification_code=sms.last_code_for("13812345122"),
        request_id="req-first-application",
    )

    with pytest.raises(VerificationInvalid):
        service.reject_admin_application(
            actor_id=super_admin.user_id,
            application_id=first.application_id,
            expected_version=first.version,
            reason="  ",
            request_id="req-empty-rejection",
        )
    rejected = service.reject_admin_application(
        actor_id=super_admin.user_id,
        application_id=first.application_id,
        expected_version=first.version,
        reason="手机号信息未核实",
        request_id="req-reject",
    )
    assert rejected.status == "rejected"
    assert rejected.rejection_reason == "手机号信息未核实"

    now[0] += timedelta(seconds=61)
    next_challenge = service.send_admin_application_code(
        user_id=applicant.user_id,
        phone="13812345122",
        request_id="req-next-code",
    )
    second = service.submit_admin_application(
        user_id=applicant.user_id,
        challenge_id=next_challenge.challenge_id,
        verification_code=sms.last_code_for("13812345122"),
        request_id="req-second-application",
    )
    history = service.list_admin_applications(actor_id=super_admin.user_id)
    assert second.application_id != first.application_id
    assert [item.status for item in history] == ["pending", "rejected"]
    pending_only = service.list_admin_applications(
        actor_id=super_admin.user_id,
        status="pending",
    )
    assert [item.application_id for item in pending_only] == [second.application_id]


def test_disabling_admin_revokes_all_sessions_and_enable_does_not_revive_them(
    test_database_engine: Engine,
) -> None:
    clean_identity_tables(test_database_engine)
    sms = FakeSmsSender()
    service = IdentityAccessService(
        sessionmaker(test_database_engine, class_=Session),
        sms_sender=sms,
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
    candidate = service.resolve_feishu_identity(
        scope="tenant-a/app-a",
        profile=FeishuProfile(subject="ou_ordinary", display_name="煎饼"),
        request_id="req-create-ordinary",
    )
    challenge = service.send_admin_application_code(
        user_id=candidate.user_id,
        phone="13812345122",
        request_id="req-send-ordinary-code",
    )
    application = service.submit_admin_application(
        user_id=candidate.user_id,
        challenge_id=challenge.challenge_id,
        verification_code=sms.last_code_for("13812345122"),
        request_id="req-submit-ordinary",
    )
    service.approve_admin_application(
        actor_id=super_admin.user_id,
        application_id=application.application_id,
        expected_version=application.version,
        request_id="req-approve-ordinary",
    )
    ordinary = service.get_user(user_id=candidate.user_id)
    web = service.issue_session(user_id=ordinary.user_id, terminal="web")
    mini = service.issue_session(user_id=ordinary.user_id, terminal="mini")
    assert (
        service.authenticate_session(token=web.access_token, terminal="web").user_id
        == ordinary.user_id
    )
    assert (
        service.authenticate_session(token=mini.access_token, terminal="mini").user_id
        == ordinary.user_id
    )

    disabled = service.set_admin_enabled(
        actor_id=super_admin.user_id,
        target_user_id=ordinary.user_id,
        enabled=False,
        expected_version=ordinary.version,
        request_id="req-disable-admin",
    )
    assert disabled.is_enabled is False
    with pytest.raises(SessionInvalid):
        service.authenticate_session(token=web.access_token, terminal="web")
    with pytest.raises(SessionInvalid):
        service.authenticate_session(token=mini.access_token, terminal="mini")

    enabled = service.set_admin_enabled(
        actor_id=super_admin.user_id,
        target_user_id=ordinary.user_id,
        enabled=True,
        expected_version=disabled.version,
        request_id="req-enable-admin",
    )
    assert enabled.is_enabled is True
    with pytest.raises(SessionInvalid):
        service.authenticate_session(token=web.access_token, terminal="web")
    with pytest.raises(PermissionDenied):
        service.set_admin_enabled(
            actor_id=super_admin.user_id,
            target_user_id=super_admin.user_id,
            enabled=False,
            expected_version=super_admin.version,
            request_id="req-disable-super",
        )


def test_wechat_phone_binding_reuses_internal_user_and_scopes_external_identity(
    test_database_engine: Engine,
) -> None:
    clean_identity_tables(test_database_engine)
    sms = FakeSmsSender()
    wechat = FakeWechatIdentity(
        scope="test-appid",
        login_profiles={
            "wx-login": WechatProfile(
                subject="openid-same",
                avatar_url="https://example.invalid/wechat-avatar.png",
            )
        },
        phone_codes={"wx-phone": "13812345122"},
    )
    service = IdentityAccessService(
        sessionmaker(test_database_engine, class_=Session),
        sms_sender=sms,
        wechat_identity=wechat,
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
        profile=FeishuProfile(subject="ou_bind", display_name="煎饼"),
        request_id="req-create-bind-user",
    )
    challenge = service.send_admin_application_code(
        user_id=applicant.user_id,
        phone="13812345122",
        request_id="req-bind-sms",
    )
    application = service.submit_admin_application(
        user_id=applicant.user_id,
        challenge_id=challenge.challenge_id,
        verification_code=sms.last_code_for("13812345122"),
        request_id="req-bind-application",
    )
    service.approve_admin_application(
        actor_id=super_admin.user_id,
        application_id=application.application_id,
        expected_version=application.version,
        request_id="req-bind-approve",
    )

    first_login = service.begin_wechat_login(login_code="wx-login", request_id="req-wx-login")
    assert first_login.status == "phone_required"
    assert first_login.binding_token
    bound = service.bind_wechat_phone(
        binding_token=first_login.binding_token,
        phone_code="wx-phone",
        request_id="req-wx-bind",
    )
    assert bound.status == "authenticated"
    assert bound.user is not None
    assert bound.user.user_id == applicant.user_id
    assert bound.user.mini_avatar_external_url == (
        "https://example.invalid/wechat-avatar.png"
    )
    assert bound.session is not None
    assert bound.session.refresh_token is not None

    web_session = service.issue_session(user_id=applicant.user_id, terminal="web")
    rotated = service.refresh_mini_session(refresh_token=bound.session.refresh_token)
    with pytest.raises(SessionInvalid):
        service.authenticate_session(token=bound.session.access_token, terminal="mini")
    service.logout_session(
        token=rotated.access_token,
        terminal="mini",
        request_id="req-wx-logout",
    )
    with pytest.raises(SessionInvalid):
        service.authenticate_session(token=rotated.access_token, terminal="mini")
    assert (
        service.authenticate_session(token=web_session.access_token, terminal="web").user_id
        == applicant.user_id
    )

    repeated = service.begin_wechat_login(
        login_code="wx-login",
        request_id="req-wx-login-repeat",
    )
    assert repeated.status == "authenticated"
    assert repeated.user is not None
    assert repeated.user.user_id == applicant.user_id
    assert repeated.binding_token is None

    production_wechat = FakeWechatIdentity(
        scope="production-appid",
        login_profiles={"wx-login": WechatProfile(subject="openid-same")},
        phone_codes={"wx-phone": "13812345122"},
    )
    production_service = IdentityAccessService(
        sessionmaker(test_database_engine, class_=Session),
        wechat_identity=production_wechat,
        token_secret=b"test-token-secret-not-for-production",
        phone_encryption_secret=b"test-phone-encryption-secret",
        phone_digest_secret=b"test-phone-digest-secret",
    )
    production_login = production_service.begin_wechat_login(
        login_code="wx-login",
        request_id="req-production-wx-login",
    )
    assert production_login.status == "phone_required"


def test_wechat_phone_binding_reports_pending_rejected_and_unmatched_states(
    test_database_engine: Engine,
) -> None:
    clean_identity_tables(test_database_engine)
    sms = FakeSmsSender()
    wechat = FakeWechatIdentity(
        scope="test-appid",
        login_profiles={
            "wx-pending": WechatProfile(subject="openid-pending"),
            "wx-rejected": WechatProfile(subject="openid-rejected"),
            "wx-unmatched": WechatProfile(subject="openid-unmatched"),
        },
        phone_codes={
            "phone-pending": "13812345122",
            "phone-rejected": "13812345123",
            "phone-unmatched": "13812345999",
        },
    )
    service = IdentityAccessService(
        sessionmaker(test_database_engine, class_=Session),
        sms_sender=sms,
        wechat_identity=wechat,
        token_secret=b"test-token-secret-not-for-production",
        phone_encryption_secret=b"test-phone-encryption-secret",
        phone_digest_secret=b"test-phone-digest-secret",
    )
    super_admin = service.bootstrap_super_admin(
        scope="tenant-a/app-a",
        profile=FeishuProfile(subject="ou_super", display_name="松子"),
        operator_source="deployment-command",
        request_id="req-bootstrap-state-super",
    )

    applications: dict[str, AdminApplicationSnapshot] = {}
    for state, phone in (("pending", "13812345122"), ("rejected", "13812345123")):
        applicant = service.resolve_feishu_identity(
            scope="tenant-a/app-a",
            profile=FeishuProfile(subject=f"ou_{state}", display_name=state),
            request_id=f"req-create-{state}",
        )
        challenge = service.send_admin_application_code(
            user_id=applicant.user_id,
            phone=phone,
            request_id=f"req-send-{state}",
        )
        applications[state] = service.submit_admin_application(
            user_id=applicant.user_id,
            challenge_id=challenge.challenge_id,
            verification_code=sms.last_code_for(phone),
            request_id=f"req-submit-{state}",
        )
    rejected = applications["rejected"]
    service.reject_admin_application(
        actor_id=super_admin.user_id,
        application_id=rejected.application_id,
        expected_version=rejected.version,
        reason="资料未核实",
        request_id="req-reject-state",
    )

    for login_code, phone_code, expected_status in (
        ("wx-pending", "phone-pending", "pending"),
        ("wx-rejected", "phone-rejected", "rejected"),
        ("wx-unmatched", "phone-unmatched", "factory_application_required"),
    ):
        login = service.begin_wechat_login(
            login_code=login_code,
            request_id=f"req-{login_code}",
        )
        assert login.binding_token is not None
        result = service.bind_wechat_phone(
            binding_token=login.binding_token,
            phone_code=phone_code,
            request_id=f"req-bind-{expected_status}",
        )
        assert result.status == expected_status
    assert result.user is not None
    assert result.user.role is None


def test_mini_avatar_is_private_idempotent_and_does_not_replace_feishu_avatar(
    test_database_engine: Engine,
) -> None:
    clean_identity_tables(test_database_engine)
    avatar_store = FakeAvatarStore(bucket="test-private-avatar-bucket")
    service = IdentityAccessService(
        sessionmaker(test_database_engine, class_=Session),
        avatar_store=avatar_store,
        token_secret=b"test-token-secret-not-for-production",
    )
    user = service.bootstrap_super_admin(
        scope="tenant-a/app-a",
        profile=FeishuProfile(
            subject="ou_avatar",
            display_name="煎饼",
            avatar_url="https://example.invalid/feishu-avatar.png",
        ),
        operator_source="deployment-command",
        request_id="req-bootstrap-avatar-user",
    )
    content = b"\x89PNG\r\n\x1a\n" + b"avatar-content"

    first = service.replace_mini_avatar(
        user_id=user.user_id,
        original_filename="avatar.png",
        mime_type="image/png",
        content=content,
        idempotency_key="avatar-request-001",
        request_id="req-avatar-first",
    )
    repeated = service.replace_mini_avatar(
        user_id=user.user_id,
        original_filename="avatar.png",
        mime_type="image/png",
        content=content,
        idempotency_key="avatar-request-001",
        request_id="req-avatar-repeat",
    )

    assert repeated.file_id == first.file_id
    assert avatar_store.object_count == 1
    refreshed_user = service.get_user(user_id=user.user_id)
    assert refreshed_user.mini_avatar_file_id == first.file_id
    assert refreshed_user.mini_avatar_external_url is None
    assert refreshed_user.feishu_avatar_url == "https://example.invalid/feishu-avatar.png"
    loaded = service.get_mini_avatar(user_id=user.user_id)
    assert loaded.content == content
    assert loaded.mime_type == "image/png"

    with pytest.raises(AvatarInvalid):
        service.replace_mini_avatar(
            user_id=user.user_id,
            original_filename="avatar.svg",
            mime_type="image/svg+xml",
            content=b"<svg></svg>",
            idempotency_key="avatar-request-invalid",
            request_id="req-avatar-invalid",
        )

    with pytest.raises(AvatarInvalid):
        service.replace_mini_avatar(
            user_id=user.user_id,
            original_filename="too-large.png",
            mime_type="image/png",
            content=b"\x89PNG\r\n\x1a\n" + b"x" * (5 * 1024 * 1024),
            idempotency_key="avatar-request-too-large",
            request_id="req-avatar-too-large",
        )
