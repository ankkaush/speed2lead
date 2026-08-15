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
    resend_from_email: str = "onboarding@resend.dev"
    sentry_dsn: Optional[str] = None

    # Phase 4 reliability (ADR 0009)
    db_command_timeout_seconds: float = 10.0
    http_connect_timeout_seconds: float = 5.0
    http_read_timeout_seconds: float = 10.0
    max_step_attempts: int = 5
    backoff_base_seconds: int = 60
    backoff_cap_seconds: int = 3600
    reconciliation_interval_seconds: int = 120

    # Phase 5 security (ADR 0010)
    webhook_signing_secret: str
    rate_limit_max_requests: int = 20
    rate_limit_window_seconds: int = 60


settings = Settings()
