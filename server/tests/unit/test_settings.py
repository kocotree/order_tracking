import pytest
from pydantic import ValidationError

from app.settings.config import Settings


def test_settings_exposes_complete_wechat_notification_template_mapping() -> None:
    settings = Settings(
        database_url="mysql+pymysql://test:test@127.0.0.1/test",
        wechat_identity_app_id="wx-test-app",
        wechat_identity_app_secret="test-secret",
        wechat_notification_admin_shipment_template_id="admin-shipment",
        wechat_notification_admin_repair_template_id="shared-repair",
        wechat_notification_factory_status_template_id="factory-status",
        wechat_notification_factory_due_template_id="factory-due",
        wechat_notification_factory_repair_template_id="shared-repair",
        wechat_notification_miniprogram_state="trial",
    )

    assert settings.wechat_notification_template_ids == {
        "admin_shipment": "admin-shipment",
        "admin_repair": "shared-repair",
        "factory_status": "factory-status",
        "factory_due": "factory-due",
        "factory_repair": "shared-repair",
    }
    assert settings.wechat_notifications_configured is True


def test_settings_rejects_partial_wechat_notification_template_mapping() -> None:
    with pytest.raises(
        ValidationError,
        match="wechat notification templates must be configured together",
    ):
        Settings(
            database_url="mysql+pymysql://test:test@127.0.0.1/test",
            wechat_identity_app_id="wx-test-app",
            wechat_identity_app_secret="test-secret",
            wechat_notification_factory_status_template_id="factory-status",
        )


def test_settings_rejects_wechat_notification_templates_without_credentials() -> None:
    with pytest.raises(
        ValidationError,
        match="wechat identity credentials are required for notifications",
    ):
        Settings(
            database_url="mysql+pymysql://test:test@127.0.0.1/test",
            wechat_identity_app_id="",
            wechat_identity_app_secret="",
            wechat_notification_admin_shipment_template_id="admin-shipment",
            wechat_notification_admin_repair_template_id="shared-repair",
            wechat_notification_factory_status_template_id="factory-status",
            wechat_notification_factory_due_template_id="factory-due",
            wechat_notification_factory_repair_template_id="shared-repair",
        )


def test_settings_rejects_enabling_wechat_notifications_without_templates() -> None:
    with pytest.raises(
        ValidationError,
        match="wechat notifications require complete template configuration",
    ):
        Settings(
            database_url="mysql+pymysql://test:test@127.0.0.1/test",
            wechat_identity_app_id="wx-test-app",
            wechat_identity_app_secret="test-secret",
            wechat_notifications_enabled=True,
            wechat_notification_admin_shipment_template_id="",
            wechat_notification_admin_repair_template_id="",
            wechat_notification_factory_status_template_id="",
            wechat_notification_factory_due_template_id="",
            wechat_notification_factory_repair_template_id="",
        )
