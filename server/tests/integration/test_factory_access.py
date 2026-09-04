from uuid import uuid4

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.identity import FeishuProfile
from app.adapters.wechat import FakeWechatIdentity, WechatProfile
from app.modules.factory_access import (
    FactoryAccessService,
    FactoryConflict,
    FactoryValidation,
)
from app.modules.identity_access import IdentityAccessService, ResourceNotFound, SessionInvalid


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


def create_admin(engine: Engine, *, subject: str = "ou_factory_admin") -> str:
    identity = IdentityAccessService(sessionmaker(engine, class_=Session))
    admin = identity.resolve_feishu_identity(
        scope="tenant-a/app-a",
        profile=FeishuProfile(
            subject=subject,
            display_name="松子",
            phone="13812345122",
        ),
        request_id=f"req-{uuid4()}",
        auto_grant_admin=True,
    )
    return admin.user_id


def create_ordinary_admin(engine: Engine, *, subject: str) -> str:
    identity = IdentityAccessService(sessionmaker(engine, class_=Session))
    user = identity.resolve_feishu_identity(
        scope="tenant-a/app-a",
        profile=FeishuProfile(
            subject=subject,
            display_name="橄榄",
            phone="13912345678",
        ),
        request_id=f"req-{uuid4()}",
        auto_grant_admin=True,
    )
    return user.user_id


def test_factory_creation_normalizes_unique_keys_and_reports_contract_completeness(
    test_database_engine: Engine,
) -> None:
    clean_factory_tables(test_database_engine)
    actor_id = create_admin(test_database_engine)
    service = FactoryAccessService(sessionmaker(test_database_engine, class_=Session))

    incomplete = service.create_factory(
        actor_id=actor_id,
        supplier_number=" a10 ",
        factory_name="禹帆",
        factory_code=" yf ",
        legal_name="温岭市新河禹帆制帽厂",
        address="",
        legal_representative="徐陈杰",
        contacts=[("王超", "13858645122")],
        request_id="req-create-yufan",
    )

    assert incomplete.supplier_number == "A10"
    assert incomplete.factory_code == "YF"
    assert incomplete.contract_complete is False
    assert incomplete.missing_contract_fields == ("单位地址",)
    assert incomplete.contacts[0].name == "王超"

    complete = service.create_factory(
        actor_id=actor_id,
        supplier_number="b02",
        factory_name="宇倩",
        factory_code="yq",
        legal_name="台州市宇倩服饰有限公司",
        address="浙江省台州市",
        legal_representative="李倩",
        contacts=[],
        request_id="req-create-yuqian",
    )
    assert complete.contract_complete is True
    assert complete.missing_contract_fields == ()

    for supplier_number, factory_name, factory_code in [
        ("A10", "另一工厂", "Q1"),
        ("C03", "禹帆", "Q2"),
        ("C04", "其他工厂", "YF"),
    ]:
        with pytest.raises(FactoryConflict):
            service.create_factory(
                actor_id=actor_id,
                supplier_number=supplier_number,
                factory_name=factory_name,
                factory_code=factory_code,
                legal_name="测试单位",
                address="测试地址",
                legal_representative="测试法人",
                contacts=[],
                request_id=f"req-duplicate-{supplier_number}",
            )


def test_factory_edit_uses_version_and_keeps_supplier_number_read_only(
    test_database_engine: Engine,
) -> None:
    clean_factory_tables(test_database_engine)
    actor_id = create_admin(test_database_engine, subject="ou_factory_editor")
    service = FactoryAccessService(sessionmaker(test_database_engine, class_=Session))
    created = service.create_factory(
        actor_id=actor_id,
        supplier_number="A10",
        factory_name="禹帆",
        factory_code="YF",
        legal_name="",
        address="",
        legal_representative="",
        contacts=[("王超", "13858645122")],
        request_id="req-create-editable",
    )

    updated = service.update_factory(
        actor_id=actor_id,
        factory_id=created.factory_id,
        expected_version=created.version,
        factory_name="禹帆制帽",
        factory_code="yf2",
        legal_name="温岭市新河禹帆制帽厂",
        address="浙江省温岭市",
        legal_representative="徐陈杰",
        contacts=[("王超", "13858645122"), ("徐陈杰", "0576-12345678")],
        request_id="req-update-factory",
    )

    assert updated.supplier_number == "A10"
    assert updated.factory_name == "禹帆制帽"
    assert updated.factory_code == "YF2"
    assert updated.version == 2
    assert updated.contract_complete is True
    assert [contact.name for contact in updated.contacts] == ["王超", "徐陈杰"]

    with pytest.raises(FactoryConflict):
        service.update_factory(
            actor_id=actor_id,
            factory_id=created.factory_id,
            expected_version=created.version,
            factory_name="过期修改",
            factory_code="OLD",
            legal_name="测试",
            address="测试",
            legal_representative="测试",
            contacts=[],
            request_id="req-stale-update",
        )

    stored = service.get_factory(actor_id=actor_id, factory_id=created.factory_id)
    assert stored.factory_name == "禹帆制帽"
    assert service.list_factories(actor_id=actor_id, keyword="王超") == [stored]


def test_factory_applicant_uses_verified_wechat_phone_and_relogs_after_approval(
    test_database_engine: Engine,
) -> None:
    clean_factory_tables(test_database_engine)
    factory = sessionmaker(test_database_engine, class_=Session)
    identity = IdentityAccessService(
        factory,
        wechat_identity=FakeWechatIdentity(
            scope="test-appid",
            login_profiles={
                "wx-factory-login": WechatProfile(subject="openid-factory-applicant")
            },
            phone_codes={"wx-factory-phone": "13912345678"},
        ),
        token_secret=b"test-token-secret-not-for-production",
        phone_encryption_secret=b"test-phone-encryption-secret",
        phone_digest_secret=b"test-phone-digest-secret",
    )
    access = FactoryAccessService(factory)
    admin_id = create_ordinary_admin(
        test_database_engine, subject="ou_factory_ordinary_reviewer"
    )
    target = access.create_factory(
        actor_id=admin_id,
        supplier_number="A10",
        factory_name="禹帆",
        factory_code="YF",
        legal_name="温岭市新河禹帆制帽厂",
        address="浙江省温岭市",
        legal_representative="徐陈杰",
        contacts=[("王超", "13858645122")],
        request_id="req-create-target-factory",
    )
    other_factory = access.create_factory(
        actor_id=admin_id,
        supplier_number="B02",
        factory_name="宇倩",
        factory_code="YQ",
        legal_name="台州市宇倩服饰有限公司",
        address="浙江省台州市",
        legal_representative="李倩",
        contacts=[],
        request_id="req-create-other-factory",
    )

    login = identity.begin_wechat_login(
        login_code="wx-factory-login", request_id="req-factory-wechat-login"
    )
    bound = identity.bind_wechat_phone(
        binding_token=login.binding_token or "",
        phone_code="wx-factory-phone",
        request_id="req-factory-phone",
    )
    assert bound.status == "factory_application_required"
    assert bound.user is not None
    assert bound.user.phone_masked == "139****5678"
    assert bound.session is not None

    application = access.submit_factory_application(
        user_id=bound.user.user_id,
        real_name="张师傅",
        position="employee",
        factory_id=target.factory_id,
        request_id="req-submit-factory-application",
    )
    assert application.status == "pending"
    assert application.position == "employee"
    assert application.requested_factory_name == "禹帆"

    approved = access.approve_factory_application(
        actor_id=admin_id,
        application_id=application.application_id,
        expected_version=application.version,
        factory_id=target.factory_id,
        request_id="req-approve-factory-application",
    )
    assert approved.status == "approved"
    assert approved.bound_factory_id == target.factory_id

    with pytest.raises(SessionInvalid):
        identity.authenticate_session(
            token=bound.session.access_token,
            terminal="mini",
        )

    relogin = identity.begin_wechat_login(
        login_code="wx-factory-login", request_id="req-factory-relogin"
    )
    assert relogin.status == "authenticated"
    assert relogin.user is not None
    assert relogin.user.role == "factory"
    assert relogin.user.factory_id == target.factory_id
    assert relogin.user.factory_position == "employee"
    assert relogin.session is not None

    own_factory = access.get_own_factory(
        user_id=relogin.user.user_id,
        factory_id=target.factory_id,
    )
    assert own_factory.factory_name == "禹帆"
    with pytest.raises(ResourceNotFound):
        access.get_own_factory(
            user_id=relogin.user.user_id,
            factory_id=other_factory.factory_id,
        )

    listed_users = access.list_factory_users(actor_id=admin_id, factory_id=target.factory_id)
    assert len(listed_users) == 1
    assert listed_users[0].real_name == "张师傅"

    disabled = access.set_factory_user_enabled(
        actor_id=admin_id,
        target_user_id=relogin.user.user_id,
        enabled=False,
        expected_version=relogin.user.version,
        request_id="req-disable-factory-user",
    )
    assert disabled.is_enabled is False
    with pytest.raises(SessionInvalid):
        identity.authenticate_session(
            token=relogin.session.access_token,
            terminal="mini",
        )
    disabled_login = identity.begin_wechat_login(
        login_code="wx-factory-login", request_id="req-disabled-factory-relogin"
    )
    assert disabled_login.status == "disabled"
    assert disabled_login.user is not None
    assert disabled_login.user.role == "factory"

    reenabled = access.set_factory_user_enabled(
        actor_id=admin_id,
        target_user_id=relogin.user.user_id,
        enabled=True,
        expected_version=disabled.version,
        request_id="req-reenable-factory-user",
    )
    assert reenabled.is_enabled is True
    with pytest.raises(SessionInvalid):
        identity.authenticate_session(
            token=relogin.session.access_token,
            terminal="mini",
        )


def test_factory_application_rejection_requires_reason_and_allows_resubmission(
    test_database_engine: Engine,
) -> None:
    clean_factory_tables(test_database_engine)
    session_factory = sessionmaker(test_database_engine, class_=Session)
    identity = IdentityAccessService(
        session_factory,
        wechat_identity=FakeWechatIdentity(
            scope="test-appid",
            login_profiles={"wx-reapply": WechatProfile(subject="openid-reapply")},
            phone_codes={"phone-reapply": "13712345678"},
        ),
        token_secret=b"test-token-secret-not-for-production",
        phone_encryption_secret=b"test-phone-encryption-secret",
        phone_digest_secret=b"test-phone-digest-secret",
    )
    access = FactoryAccessService(session_factory)
    admin_id = create_ordinary_admin(test_database_engine, subject="ou_reapply_reviewer")
    factory = access.create_factory(
        actor_id=admin_id,
        supplier_number="A10",
        factory_name="禹帆",
        factory_code="YF",
        legal_name="温岭市新河禹帆制帽厂",
        address="浙江省温岭市",
        legal_representative="徐陈杰",
        contacts=[("王超", "13858645122")],
        request_id="req-create-reapply-factory",
    )
    login = identity.begin_wechat_login(
        login_code="wx-reapply", request_id="req-reapply-login"
    )
    bound = identity.bind_wechat_phone(
        binding_token=login.binding_token or "",
        phone_code="phone-reapply",
        request_id="req-reapply-phone",
    )
    assert bound.user is not None
    first = access.submit_factory_application(
        user_id=bound.user.user_id,
        real_name="张师傅",
        position="owner",
        factory_id=factory.factory_id,
        request_id="req-first-application",
    )

    with pytest.raises(FactoryValidation):
        access.reject_factory_application(
            actor_id=admin_id,
            application_id=first.application_id,
            expected_version=first.version,
            reason=" ",
            request_id="req-empty-rejection",
        )

    rejected = access.reject_factory_application(
        actor_id=admin_id,
        application_id=first.application_id,
        expected_version=first.version,
        reason="工厂选择有误",
        request_id="req-reject-application",
    )
    assert rejected.status == "rejected"
    assert rejected.rejection_reason == "工厂选择有误"
    with pytest.raises(FactoryConflict):
        access.approve_factory_application(
            actor_id=admin_id,
            application_id=first.application_id,
            expected_version=first.version,
            factory_id=factory.factory_id,
            request_id="req-duplicate-review",
        )

    second = access.submit_factory_application(
        user_id=bound.user.user_id,
        real_name="张师傅",
        position="employee",
        factory_id=factory.factory_id,
        request_id="req-second-application",
    )
    assert second.application_id != first.application_id
    assert second.status == "pending"
    assert second.position == "employee"
    history = access.list_factory_applications(actor_id=admin_id)
    assert [item.status for item in history] == ["pending", "rejected"]
