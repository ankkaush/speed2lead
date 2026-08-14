from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """App configuration, loaded from environment variables / .env.

    No business logic reads DATABASE_URL, HUBSPOT_ACCESS_TOKEN, SLACK_WEBHOOK_URL, or
    RESEND_API_KEY yet (Phase 3+), so they're optional here. Each becomes a required
    field the moment the code that depends on it lands, so a missing value fails fast
    at startup rather than surfacing as a confusing runtime error mid-request.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    database_url: Optional[str] = None
    hubspot_access_token: Optional[str] = None
    slack_webhook_url: Optional[str] = None
    resend_api_key: Optional[str] = None
    sentry_dsn: Optional[str] = None


settings = Settings()
