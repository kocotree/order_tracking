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
    avatar_bucket: str = "unconfigured-avatar"
    feishu_order_app_id: str = ""
    feishu_order_app_secret: str = ""
    feishu_order_app_token: str = ""
    feishu_order_table_id: str = ""
    feishu_order_view_id: str = ""
    private_file_endpoint: str = ""
    private_file_access_key: str = ""
    private_file_secret_key: str = ""
    private_file_bucket: str = "unconfigured-contract-files"
    private_file_secure: bool = True
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
        if self.app_env == "production" and not self.web_cookie_secure:
            raise ValueError("secure web cookies are required in production")
        if bool(self.wechat_identity_app_id) != bool(self.wechat_identity_app_secret):
            raise ValueError("wechat identity app id and secret must be configured together")
        if not 0 <= self.notification_due_scan_hour <= 23:
            raise ValueError("notification due scan hour must be between 0 and 23")
        return self
