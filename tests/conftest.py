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


@pytest_asyncio.fixture
async def client():
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


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
