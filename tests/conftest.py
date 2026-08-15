import hashlib
import hmac
import json

import asyncpg
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.main import app

# Tests run against the real Supabase Postgres project (ADR 0003/0007), not a mock —
# consistent with the project's preference for real dependencies over mocks where
# feasible. Test data is isolated by a dedicated email prefix and cleaned up after
# every test. example.com is RFC 2606-reserved (guaranteed never a real live domain);
# pydantic's email-validator rejects the more obvious .invalid/.test TLDs outright, so
# this is the reserved option that actually passes validation.
TEST_EMAIL_DOMAIN = "example.com"
TEST_EMAIL_LOCAL_PREFIX = "speed-to-lead-test-"


@pytest_asyncio.fixture(autouse=True)
def _reset_rate_limiter():
    """The rate limiter's state is a module-level dict (app/rate_limit.py), shared across
    the whole test run since every test client shares the same fake client IP under
    httpx's ASGITransport. Without resetting it, unrelated tests could trip the 20-
    requests/60s limit purely from accumulated test traffic, not from anything the test
    itself is checking."""
    from app.rate_limit import _request_log

    _request_log.clear()
    yield
    _request_log.clear()


@pytest_asyncio.fixture(autouse=True)
def _no_real_integration_calls(monkeypatch):
    """Real HubSpot/Slack/Resend/Sentry credentials live in this dev environment's .env
    (Phase 4/6 real-integration work), but the automated suite must stay side-effect-free
    -- no real Slack messages, HubSpot contacts, emails, or Sentry events on every test
    run. Forced off globally here rather than per-test; test_adapters.py additionally
    sets the first three explicitly per test for local readability.

    sentry_dsn specifically must be unset BEFORE the lifespan runs (i.e. before the
    `client` fixture's `async with app.router.lifespan_context(app)`), since
    sentry_sdk.init() is called once at startup, not per-request -- pytest runs autouse
    fixtures before explicitly-requested ones at the same scope, so this ordering is
    guaranteed as long as this fixture doesn't itself depend on `client`."""
    monkeypatch.setattr(settings, "hubspot_access_token", None)
    monkeypatch.setattr(settings, "slack_webhook_url", None)
    monkeypatch.setattr(settings, "resend_api_key", None)
    monkeypatch.setattr(settings, "sentry_dsn", None)


def signed_post_kwargs(payload: dict, extra_headers: dict = None) -> dict:
    """Builds the (content=, headers=) kwargs for a correctly-signed POST /leads call
    (ADR 0010). Serializes the body ourselves and signs those exact bytes -- rather than
    passing json=payload to httpx and hoping its internal serialization matches what we
    sign -- so there's no risk of a subtle mismatch producing a false signature failure."""
    body = json.dumps(payload).encode("utf-8")
    signature = hmac.new(settings.webhook_signing_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    headers = {"Content-Type": "application/json", "X-Webhook-Signature": signature}
    if extra_headers:
        headers.update(extra_headers)
    return {"content": body, "headers": headers}


@pytest_asyncio.fixture
async def client():
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest_asyncio.fixture
async def db_pool():
    """A standalone pool for tests that exercise the repo layer directly (e.g.
    reconciliation eligibility), independent of the app's own pool lifecycle."""
    pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=2)
    try:
        yield pool
    finally:
        await pool.close()


@pytest_asyncio.fixture(autouse=True)
async def cleanup_test_leads():
    yield
    conn = await asyncpg.connect(settings.database_url)
    try:
        await conn.execute(
            "DELETE FROM leads WHERE email LIKE $1",
            f"{TEST_EMAIL_LOCAL_PREFIX}%@{TEST_EMAIL_DOMAIN}",
        )
    finally:
        await conn.close()
