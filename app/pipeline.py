import logging
from typing import Dict

import asyncpg
import httpx

from app import leads_repo
from app.adapters import ack, crm, notify
from app.adapters.base import StepAdapter

logger = logging.getLogger("speed_to_lead")

# The only place a provider is chosen (ADR 0013): swap HubSpot/Slack/Resend for another
# provider by writing a new module that satisfies StepAdapter (app/adapters/base.py) and
# changing the corresponding entry here. Nothing else in this file, or in leads_repo.py/
# routes/leads.py/reconciliation.py, references a provider by name.
_STEP_ADAPTERS: Dict[str, StepAdapter] = {"crm": crm.attempt, "notify": notify.attempt, "ack": ack.attempt}
STEPS = ("crm", "notify", "ack")


async def attempt_step(
    pool: asyncpg.Pool, http_client: httpx.AsyncClient, lead, step: str, max_attempts: int
) -> None:
    """Runs one adapter call for one lead/step and persists the outcome. Used by both the
    synchronous first attempt (in the request path) and the reconciliation sweep — one
    code path, so the retry state machine only exists in one place."""
    adapter_fn = _STEP_ADAPTERS[step]
    try:
        result = await adapter_fn(lead, http_client)
    except Exception:
        logger.exception(f"step_attempt_unexpected_error step={step} lead_id={lead['id']}")
        return

    await leads_repo.record_step_attempt(
        pool, lead_id=lead["id"], step=step, result=result, max_attempts=max_attempts
    )


async def attempt_all_steps(
    pool: asyncpg.Pool, http_client: httpx.AsyncClient, lead, max_attempts: int
) -> None:
    """Best-effort, one attempt each, independently — one step failing must never
    prevent attempting (or hide the outcome of) the other two."""
    for step in STEPS:
        await attempt_step(pool, http_client, lead, step, max_attempts)
