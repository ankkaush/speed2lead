import asyncio

from tests.conftest import TEST_EMAIL_DOMAIN, TEST_EMAIL_LOCAL_PREFIX, signed_post_kwargs


async def test_concurrent_identical_requests_create_exactly_one_lead(client, db_pool):
    """This is the actual scenario INSERT ... ON CONFLICT DO NOTHING (ADR 0008) was
    built to make safe -- a check-then-insert would have a race window here that this
    test would catch. Every earlier duplicate test sent requests sequentially, which
    never exercises the race at all; asyncio.gather here genuinely interleaves these
    against the app's real connection pool."""
    payload = {
        "name": "Concurrency Test",
        "email": f"{TEST_EMAIL_LOCAL_PREFIX}concurrency@{TEST_EMAIL_DOMAIN}",
        "message": "Testing the UNIQUE constraint under real concurrency.",
    }
    headers = {"Idempotency-Key": "concurrency-test-fixed-key"}
    kwargs = signed_post_kwargs(payload, headers)

    responses = await asyncio.gather(*[client.post("/leads", **kwargs) for _ in range(10)])

    assert all(r.status_code == 200 for r in responses)

    duplicate_flags = [r.json()["duplicate"] for r in responses]
    assert duplicate_flags.count(False) == 1, "exactly one request should have created the lead"
    assert duplicate_flags.count(True) == 9

    ids = {r.json()["id"] for r in responses}
    assert len(ids) == 1, "every response must reference the same lead"

    async with db_pool.acquire() as conn:
        count = await conn.fetchval("SELECT count(*) FROM leads WHERE email = $1", payload["email"])
    assert count == 1, "the UNIQUE constraint must have prevented any duplicate row from existing"
