from datetime import datetime
from typing import Literal
from urllib.parse import urlparse

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    app_env: str = "development"
    log_level: str = "INFO"
    identity_token_secret: str = ""
    phone_encryption_secret: str = ""
    phone_digest_secret: str = ""
    feishu_identity_scope: str = "unconfigured-feishu"
    feishu_identity_app_id: str = ""
    feishu_identity_app_secret: str = ""
    feishu_identity_redirect_uri: str = ""
    web_cookie_secure: bool = True
    wechat_identity_scope: str = "unconfigured-wechat"
    wechat_identity_app_id: str = ""
    wechat_identity_app_secret: str = ""
    wechat_notifications_enabled: bool = False
    feishu_notifications_enabled: bool = False
    ops_alerts_enabled: bool = False
    wechat_notification_admin_shipment_template_id: str = ""
    wechat_notification_admin_repair_template_id: str = ""
    wechat_notification_factory_status_template_id: str = ""
    wechat_notification_factory_due_template_id: str = ""
    wechat_notification_factory_repair_template_id: str = ""
    wechat_notification_miniprogram_state: Literal["developer", "trial", "formal"] = (
        "formal"
    )
    feishu_order_app_id: str = ""
    feishu_order_app_secret: str = ""
    feishu_order_app_token: str = ""
    feishu_order_table_id: str = ""
    feishu_order_view_id: str = ""
    oss_region: str = ""
    oss_endpoint: str = ""
    oss_access_key_id: str = ""
    oss_access_key_secret: str = ""
    oss_bucket: str = "unconfigured-private-files"
    jst_product_endpoint: str = "https://openapi.jushuitan.com"
    jst_product_app_key: str = ""
    jst_product_app_secret: str = ""
    jst_product_token_cache_path: str = "/tmp/order-tracking/jst-token.json"
    jst_product_initial_sync_begin: str = ""
    jst_product_page_size: int = 50
    admin_web_base_url: str = ""
    ops_alert_recipient_user_id: str = ""
    notification_due_scan_hour: int = 9

    model_config = SettingsConfigDict(
        env_prefix="ORDER_TRACKING_",
        env_file=(".env", "../.env"),
        extra="ignore",
    )

    @model_validator(mode="after")
    def require_identity_secrets_outside_local_development(self) -> "Settings":
        if self.app_env in {"shared_test", "production"} and not all(
            [
                self.identity_token_secret,
                self.phone_encryption_secret,
                self.phone_digest_secret,
            ]
        ):
            raise ValueError("identity security secrets are required outside local development")
        deployment_env = self.app_env in {"shared_test", "production"}
        if deployment_env and not self.web_cookie_secure:
            raise ValueError(
                "secure web cookies are required in shared_test and production"
            )
        if deployment_env:
            database = urlparse(self.database_url)
            if database.username == "root" or database.hostname in {
                "127.0.0.1",
                "::1",
                "localhost",
            }:
                raise ValueError(
                    "deployment requires a least-privilege non-loopback database URL"
                )
        if bool(self.wechat_identity_app_id) != bool(self.wechat_identity_app_secret):
            raise ValueError("wechat identity app id and secret must be configured together")
        template_ids = self.wechat_notification_template_ids
        if any(template_ids.values()) and not all(template_ids.values()):
            raise ValueError("wechat notification templates must be configured together")
        if all(template_ids.values()) and not self.wechat_identity_app_id:
            raise ValueError(
                "wechat identity credentials are required for notifications"
            )
        if self.wechat_notifications_enabled and not all(template_ids.values()):
            raise ValueError(
                "wechat notifications require complete template configuration"
            )
        if not 0 <= self.notification_due_scan_hour <= 23:
            raise ValueError("notification due scan hour must be between 0 and 23")
        if not 1 <= self.jst_product_page_size <= 50:
            raise ValueError("jst product page size must be between 1 and 50")
        if deployment_env:
            expected_miniprogram_state = (
                "trial" if self.app_env == "shared_test" else "formal"
            )
            if self.wechat_notification_miniprogram_state != expected_miniprogram_state:
                raise ValueError(
                    f"{self.app_env} requires {expected_miniprogram_state} "
                    "WeChat Mini Program delivery"
                )
            if self.jst_product_initial_sync_begin:
                try:
                    datetime.fromisoformat(self.jst_product_initial_sync_begin)
                except ValueError as error:
                    raise ValueError(
                        "product initial sync begin must be an ISO 8601 datetime"
                    ) from error
        if deployment_env and not self._real_external_adapters_are_complete():
            raise ValueError(
                f"{self.app_env} requires complete real external adapter configuration"
            )
        return self

    def _real_external_adapters_are_complete(self) -> bool:
        feishu_app_id = self.feishu_identity_app_id or self.feishu_order_app_id
        feishu_app_secret = self.feishu_identity_app_secret or self.feishu_order_app_secret
        required_values = (
            feishu_app_id,
            feishu_app_secret,
            self.feishu_identity_redirect_uri,
            self.wechat_identity_app_id,
            self.wechat_identity_app_secret,
            self.feishu_order_app_id,
            self.feishu_order_app_secret,
            self.feishu_order_app_token,
            self.feishu_order_table_id,
            self.feishu_order_view_id,
            self.oss_region,
            self.oss_endpoint,
            self.oss_access_key_id,
            self.oss_access_key_secret,
            self.oss_bucket,
            self.jst_product_app_key,
            self.jst_product_app_secret,
            self.jst_product_token_cache_path,
            self.jst_product_initial_sync_begin,
            self.admin_web_base_url,
            self.ops_alert_recipient_user_id,
            *self.wechat_notification_template_ids.values(),
        )
        if not all(self._is_real_value(value) for value in required_values):
            return False
        return all(
            self._is_https_url(value)
            for value in (
                self.feishu_identity_redirect_uri,
                self.admin_web_base_url,
                self.jst_product_endpoint,
                self.oss_endpoint,
            )
        )

    @staticmethod
    def _is_real_value(value: str) -> bool:
        normalized = value.strip().lower()
        return bool(normalized) and not any(
            marker in normalized
            for marker in ("change-me", "example.invalid", "replace-with", "unconfigured")
        )

    @staticmethod
    def _is_https_url(value: str) -> bool:
        parsed = urlparse(value)
        return parsed.scheme == "https" and bool(parsed.hostname)

    @property
    def wechat_notification_template_ids(self) -> dict[str, str]:
        return {
            "admin_shipment": self.wechat_notification_admin_shipment_template_id,
            "admin_repair": self.wechat_notification_admin_repair_template_id,
            "factory_status": self.wechat_notification_factory_status_template_id,
            "factory_due": self.wechat_notification_factory_due_template_id,
            "factory_repair": self.wechat_notification_factory_repair_template_id,
        }

    @property
    def wechat_notifications_configured(self) -> bool:
        return all(self.wechat_notification_template_ids.values())
