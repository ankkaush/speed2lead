import asyncio

import asyncpg
import httpx

import app.reconciliation as reconciliation_module
import app.routes.leads as leads_route_module
from app.pipeline import attempt_all_steps
from tests.conftest import TEST_EMAIL_DOMAIN, TEST_EMAIL_LOCAL_PREFIX, signed_post_kwargs


def _payload(email_suffix: str) -> dict:
    return {
        "name": "Failure Injection Test",
        "email": f"{TEST_EMAIL_LOCAL_PREFIX}{email_suffix}@{TEST_EMAIL_DOMAIN}",
        "message": "Simulating a failure to prove the handling actually works.",
    }


async def test_db_failure_at_intake_returns_503(client, monkeypatch):
    """Phase 4 built a narrow try/except around persistence specifically for this
    scenario -- never actually triggered until now. Simulating the exact exception type
    it's designed to catch, not a generic one, so this proves the real code path."""

    async def raise_connection_error(*args, **kwargs):
        raise asyncpg.PostgresConnectionError("simulated DB outage")

    monkeypatch.setattr(leads_route_module, "insert_or_get_lead", raise_connection_error)

    kwargs = signed_post_kwargs(_payload("db-failure"))
    resp = await client.post("/leads", **kwargs)

    assert resp.status_code == 503
    assert resp.json()["detail"] == "Temporarily unavailable, please retry"


async def test_health_check_returns_503_when_db_unreachable(client, monkeypatch):
    from app.main import app

    class _BrokenPool:
        def acquire(self):
            raise ConnectionError("simulated DB outage")

    monkeypatch.setattr(app.state, "db_pool", _BrokenPool())

    resp = await client.get("/health")
    assert resp.status_code == 503
    assert resp.json()["status"] == "error"


async def test_unhandled_exception_returns_generic_500(client_like_real_deployment, monkeypatch):
    """A genuinely unexpected bug (not one of the specific handled failure types)
    anywhere in the request path must still produce a safe, generic response -- never a
    stack trace or internal detail. Forcing this via get_lead_status, which runs after
    persistence succeeds, so this proves the global handler catches bugs anywhere in the
    request, not just ones we anticipated.

    Uses client_like_real_deployment, not the default client fixture: this is exactly
    the test that needs to see what a real caller receives (the HTTP response our
    exception handler sent), not httpx's debug-friendly re-raise of the underlying
    exception into the test process."""

    async def raise_unexpected(*args, **kwargs):
        raise RuntimeError("simulated unexpected bug, unrelated to DB/auth/rate-limit")

    monkeypatch.setattr(leads_route_module, "get_lead_status", raise_unexpected)

    kwargs = signed_post_kwargs(_payload("unhandled-exception"))
    resp = await client_like_real_deployment.post("/leads", **kwargs)

    assert resp.status_code == 500
    assert resp.json() == {"detail": "Internal server error"}
    assert "RuntimeError" not in resp.text
    assert "simulated unexpected bug" not in resp.text


async def test_reconciliation_loop_survives_a_sweep_exception(db_pool):
    """The sweep's own try/except (app/reconciliation.py) has never actually been
    exercised. A sweep that raises once must not kill the loop -- the next tick should
    still run."""
    call_count = {"n": 0}

    async def flaky_sweep(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("simulated sweep failure")
        return 0

    import app.reconciliation as recon

    original_run_sweep = recon.run_sweep
    recon.run_sweep = flaky_sweep
    try:
        http_client = httpx.AsyncClient(timeout=1)
        task = asyncio.create_task(
            reconciliation_module.reconciliation_loop(
                db_pool, http_client, interval_seconds=0.05, max_attempts=5, base_seconds=1, cap_seconds=10
            )
        )
        await asyncio.sleep(0.3)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await http_client.aclose()
    finally:
        recon.run_sweep = original_run_sweep

    assert call_count["n"] >= 2, "loop should have survived the first failure and run again"


async def test_pipeline_step_independence_when_one_adapter_raises(db_pool, monkeypatch):
    """Phase 4's independence claim was proven manually once (a real broken Slack URL).
    This proves it in code: an adapter that raises an outright exception (not just a
    classified failure) must not prevent the other two steps from running."""
    # app.pipeline._STEP_ADAPTERS captures a direct reference to notify.attempt at
    # import time (a dict built once at module load), not a live lookup -- patching the
    # app.adapters.notify module's own attribute afterward wouldn't affect the dict's
    # already-captured value, so the dict entry itself must be replaced.
    import app.pipeline as pipeline_module

    async def broken_notify(*args, **kwargs):
        raise RuntimeError("simulated adapter bug")

    monkeypatch.setitem(pipeline_module._STEP_ADAPTERS, "notify", broken_notify)

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO leads (idempotency_key, idempotency_source, name, email, message)
            VALUES ($1, 'client', 'Pipeline Independence Test', $2, 'testing')
            RETURNING id
            """,
            "pipeline-independence-test-key",
            f"{TEST_EMAIL_LOCAL_PREFIX}pipeline-independence@{TEST_EMAIL_DOMAIN}",
        )
        lead_id = row["id"]

    lead = {
        "id": lead_id,
        "name": "Pipeline Independence Test",
        "email": f"{TEST_EMAIL_LOCAL_PREFIX}pipeline-independence@{TEST_EMAIL_DOMAIN}",
        "phone": None,
        "message": "testing",
        "source": None,
    }

    http_client = httpx.AsyncClient(timeout=5)
    try:
        await attempt_all_steps(db_pool, http_client, lead, max_attempts=5)
    finally:
        await http_client.aclose()

    async with db_pool.acquire() as conn:
        final = await conn.fetchrow(
            "SELECT crm_status, notify_status, ack_status, notify_attempts FROM leads WHERE id = $1", lead_id
        )
        await conn.execute("DELETE FROM leads WHERE id = $1", lead_id)

    # crm/ack still ran to completion (unconfigured in this test env -> 'failed', same
    # as every other test) despite notify raising an outright exception.
    assert final["crm_status"] == "failed"
    assert final["ack_status"] == "failed"
    # notify never got a chance to update its own status -- pipeline.attempt_step caught
    # the exception, logged it, and moved on without writing anything for this step.
    assert final["notify_status"] == "pending"
    assert final["notify_attempts"] == 0
