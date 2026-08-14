import asyncio
import logging

import asyncpg
import httpx

from app import leads_repo
from app.pipeline import STEPS, attempt_step

logger = logging.getLogger("speed_to_lead")


async def run_sweep(
    pool: asyncpg.Pool,
    http_client: httpx.AsyncClient,
    *,
    max_attempts: int,
    base_seconds: int,
    cap_seconds: int,
) -> int:
    """One sweep pass: for each step, fetch rows eligible for retry (per the backoff
    formula in leads_repo.fetch_eligible_for_retry) and retry that one step. Returns the
    number of attempts made, for logging."""
    attempts_made = 0
    for step in STEPS:
        rows = await leads_repo.fetch_eligible_for_retry(
            pool, step=step, max_attempts=max_attempts, base_seconds=base_seconds, cap_seconds=cap_seconds
        )
        for row in rows:
            await attempt_step(pool, http_client, row, step, max_attempts)
            attempts_made += 1
    return attempts_made


async def reconciliation_loop(
    pool: asyncpg.Pool,
    http_client: httpx.AsyncClient,
    *,
    interval_seconds: int,
    max_attempts: int,
    base_seconds: int,
    cap_seconds: int,
) -> None:
    """Runs forever (until cancelled at shutdown), independent of any single request's
    lifecycle — this is what catches a lead left stuck 'pending' by a transient failure
    or a crash mid-processing, which nothing else in the system would otherwise notice."""
    while True:
        try:
            attempts_made = await run_sweep(
                pool, http_client, max_attempts=max_attempts, base_seconds=base_seconds, cap_seconds=cap_seconds
            )
            if attempts_made:
                logger.info(f"reconciliation_sweep attempts_made={attempts_made}")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("reconciliation_sweep_failed")
        await asyncio.sleep(interval_seconds)
