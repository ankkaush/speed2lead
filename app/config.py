from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """App configuration, loaded from environment variables / .env.

    A field becomes required the moment the code that depends on it lands, so a missing
    value fails fast at startup rather than surfacing as a confusing runtime error
    mid-request. DATABASE_URL is required as of Phase 3 (the app now connects to Postgres
    on startup). HUBSPOT_ACCESS_TOKEN, SLACK_WEBHOOK_URL, and RESEND_API_KEY are still
    unused (Phase 4+) and stay optional until that code lands.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    database_url: str
    idempotency_bucket_minutes: int = 5
    hubspot_access_token: Optional[str] = None
    slack_webhook_url: Optional[str] = None
    resend_api_key: Optional[str] = None
    sentry_dsn: Optional[str] = None


settings = Settings()
