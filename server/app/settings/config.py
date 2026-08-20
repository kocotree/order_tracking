from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    app_env: str = "development"
    log_level: str = "INFO"

    model_config = SettingsConfigDict(
        env_prefix="ORDER_TRACKING_",
        env_file=(".env", "../.env"),
        extra="ignore",
    )
