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
    wechat_identity_scope: str = "unconfigured-wechat"
    avatar_bucket: str = "unconfigured-avatar"
    feishu_order_app_id: str = ""
    feishu_order_app_secret: str = ""
    feishu_order_app_token: str = ""
    feishu_order_table_id: str = ""
    feishu_order_view_id: str = ""

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
        return self
