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
def _no_real_integration_calls(monkeypatch):
    """Real HubSpot/Slack/Resend credentials live in this dev environment's .env (Phase
    4 real-integration work), but the automated suite must stay side-effect-free -- no
    real Slack messages, HubSpot contacts, or emails on every test run. Forced off
    globally here rather than per-test; test_adapters.py additionally sets this
    explicitly per test for local readability."""
    monkeypatch.setattr(settings, "hubspot_access_token", None)
    monkeypatch.setattr(settings, "slack_webhook_url", None)
    monkeypatch.setattr(settings, "resend_api_key", None)


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
