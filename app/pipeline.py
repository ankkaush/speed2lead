import logging
from typing import Dict

import asyncpg
import httpx
import sentry_sdk

from app import leads_repo
from app.adapters import ack, crm, notify
from app.adapters.base import StepAdapter, StepOutcome, StepResult

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
    code path, so the retry state machine only exists in one place.

    ADR 0015: an adapter raising an exception the adapter itself doesn't classify (a bug,
    an unexpected library error) used to be logged locally and silently dropped -- no
    Sentry alert, no attempt recorded, meaning a persistently-broken adapter would be
    "retried" by the sweep forever with zero visible progress, since every retry hit the
    identical unhandled exception. Treated as a transient failure now: it still counts
    against the attempt budget (so a truly stuck row eventually reaches the existing
    give-up-and-alert path in leads_repo.record_step_attempt), and is reported to Sentry
    immediately rather than only when the budget is exhausted.

    Deliberately uses type(exc).__name__, never str(exc), in what gets stored: an
    exception's message can itself contain sensitive data (httpx's LocalProtocolError
    includes the raw header value that triggered it, which is exactly how a misconfigured
    secret ended up in this project's own logs during Phase 8 deployment) -- the class
    name is enough to diagnose from Sentry's full traceback without risking a second copy
    of a leaked secret landing in this database.
    """
    adapter_fn = _STEP_ADAPTERS[step]
    try:
        result = await adapter_fn(lead, http_client)
    except Exception as exc:
        logger.exception(f"step_attempt_unexpected_error step={step} lead_id={lead['id']}")
        sentry_sdk.capture_exception(exc)
        result = StepResult(
            outcome=StepOutcome.TRANSIENT_FAILURE,
            error=f"unexpected error in adapter: {type(exc).__name__}",
        )

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
