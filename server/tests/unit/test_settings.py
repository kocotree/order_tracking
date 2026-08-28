import pytest
from pydantic import ValidationError

from app.settings.config import Settings


def _deployment_settings(*, app_env: str) -> dict[str, object]:
    miniprogram_state = "trial" if app_env == "shared_test" else "formal"
    return {
        "database_url": "mysql+pymysql://app:secret@mysql.internal/order_tracking",
        "app_env": app_env,
        "identity_token_secret": "fixed-token-secret",
        "phone_encryption_secret": "fixed-encryption-secret",
        "phone_digest_secret": "fixed-digest-secret",
        "web_cookie_secure": True,
        "feishu_identity_app_id": "cli_app_id",
        "feishu_identity_app_secret": "app-secret",
        "feishu_identity_redirect_uri": "https://web.test/auth/callback",
        "wechat_identity_app_id": "wx-app-id",
        "wechat_identity_app_secret": "wx-secret",
        "feishu_order_app_id": "cli_order_app",
        "feishu_order_app_secret": "order-secret",
        "feishu_order_app_token": "base-token",
        "feishu_order_table_id": "table-id",
        "feishu_order_view_id": "view-id",
        "private_file_endpoint": "minio.internal:9000",
        "private_file_access_key": "access-key",
        "private_file_secret_key": "secret-key",
        "private_file_bucket": "contracts-private",
        "avatar_bucket": "avatars-private",
        "product_image_bucket": "products-private",
        "jst_product_app_key": "app-key",
        "jst_product_app_secret": "app-secret",
        "jst_product_token_cache_path": "/var/lib/order-tracking/jst/token.json",
        "jst_product_initial_sync_begin": "2026-01-01T00:00:00+08:00",
        "admin_web_base_url": "https://web.test",
        "ops_alert_recipient_user_id": "ops-user",
        "wechat_notification_admin_shipment_template_id": "admin-shipment",
        "wechat_notification_admin_repair_template_id": "admin-repair",
        "wechat_notification_factory_status_template_id": "factory-status",
        "wechat_notification_factory_due_template_id": "factory-due",
        "wechat_notification_factory_repair_template_id": "factory-repair",
        "wechat_notification_miniprogram_state": miniprogram_state,
    }


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


def test_shared_test_rejects_missing_real_external_adapters() -> None:
    with pytest.raises(
        ValidationError,
        match="shared_test requires complete real external adapter configuration",
    ):
        Settings(
            database_url="mysql+pymysql://order_test:test@mysql.test/order_tracking_test",
            app_env="shared_test",
            identity_token_secret="fixed-token-secret",
            phone_encryption_secret="fixed-encryption-secret",
            phone_digest_secret="fixed-digest-secret",
            web_cookie_secure=True,
            wechat_notification_miniprogram_state="trial",
        )


def test_shared_test_rejects_insecure_web_cookies() -> None:
    with pytest.raises(
        ValidationError,
        match="secure web cookies are required in shared_test and production",
    ):
        Settings(
            database_url="mysql+pymysql://order_test:test@mysql.test/order_tracking_test",
            app_env="shared_test",
            identity_token_secret="fixed-token-secret",
            phone_encryption_secret="fixed-encryption-secret",
            phone_digest_secret="fixed-digest-secret",
            web_cookie_secure=False,
        )


def test_shared_test_requires_trial_miniprogram_delivery() -> None:
    values = _deployment_settings(app_env="shared_test")
    values["wechat_notification_miniprogram_state"] = "formal"

    with pytest.raises(ValidationError, match="shared_test requires trial"):
        Settings(**values)  # type: ignore[arg-type]


def test_production_requires_formal_miniprogram_delivery() -> None:
    values = _deployment_settings(app_env="production")
    values["wechat_notification_miniprogram_state"] = "trial"

    with pytest.raises(ValidationError, match="production requires formal"):
        Settings(**values)  # type: ignore[arg-type]


def test_deployment_rejects_invalid_product_sync_begin() -> None:
    values = _deployment_settings(app_env="shared_test")
    values["jst_product_initial_sync_begin"] = "not-a-date"

    with pytest.raises(ValidationError, match="product initial sync begin"):
        Settings(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "database_url",
    [
        "mysql+pymysql://root:secret@mysql.internal/order_tracking",
        "mysql+pymysql://app:secret@127.0.0.1/order_tracking",
    ],
)
def test_deployment_rejects_privileged_or_loopback_database_url(
    database_url: str,
) -> None:
    values = _deployment_settings(app_env="shared_test")
    values["database_url"] = database_url

    with pytest.raises(ValidationError, match="least-privilege non-loopback database"):
        Settings(**values)  # type: ignore[arg-type]
