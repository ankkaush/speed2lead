import asyncpg

from app.adapters.base import StepResult

_INSERT_LEAD = """
INSERT INTO leads (idempotency_key, idempotency_source, name, email, phone, message, source)
VALUES ($1, $2, $3, $4, $5, $6, $7)
ON CONFLICT (idempotency_key) DO NOTHING
RETURNING id, crm_status, notify_status, ack_status, received_at
"""

_SELECT_BY_KEY = """
SELECT id, crm_status, notify_status, ack_status, received_at
FROM leads
WHERE idempotency_key = $1
"""


async def insert_or_get_lead(
    pool: asyncpg.Pool,
    *,
    idempotency_key: str,
    idempotency_source: str,
    name: str,
    email: str,
    phone: str,
    message: str,
    source: str,
):
    """Atomic insert-or-detect-duplicate (ADR 0008): the UNIQUE constraint on
    idempotency_key, combined with ON CONFLICT DO NOTHING, is what makes this safe under
    concurrent identical requests — a check-then-insert at the application level would
    have a race condition here.

    Returns (row, duplicate: bool).
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            _INSERT_LEAD,
            idempotency_key,
            idempotency_source,
            name,
            email,
            phone,
            message,
            source,
        )
        if row is not None:
            return row, False

        row = await conn.fetchrow(_SELECT_BY_KEY, idempotency_key)
        return row, True


_SELECT_LEAD_STATUS = """
SELECT id, crm_status, notify_status, ack_status, received_at
FROM leads
WHERE id = $1
"""


async def get_lead_status(pool: asyncpg.Pool, lead_id):
    async with pool.acquire() as conn:
        return await conn.fetchrow(_SELECT_LEAD_STATUS, lead_id)


# One UPDATE template per step (ADR 0009): the CASE expression is the whole state
# machine for a step, evaluated atomically in the database rather than as a Python
# read-modify-write — success -> 'success'; a permanent failure -> 'failed' immediately,
# since retrying it can't help; a transient failure -> 'failed' once attempts reach the
# cap, otherwise stays 'pending' (still eligible for another try). Only the CRM step has
# an external_id column to populate.
_STEP_UPDATE_QUERIES = {
    "crm": """
        UPDATE leads
        SET crm_status = CASE
                WHEN $2 = 'success' THEN 'success'::step_status
                WHEN $2 = 'permanent_failure' THEN 'failed'::step_status
                WHEN crm_attempts + 1 >= $4 THEN 'failed'::step_status
                ELSE 'pending'::step_status
            END,
            crm_attempts = crm_attempts + 1,
            crm_last_attempted_at = now(),
            crm_error = $3,
            crm_external_id = COALESCE($5, crm_external_id)
        WHERE id = $1
        RETURNING crm_status, crm_attempts
    """,
    "notify": """
        UPDATE leads
        SET notify_status = CASE
                WHEN $2 = 'success' THEN 'success'::step_status
                WHEN $2 = 'permanent_failure' THEN 'failed'::step_status
                WHEN notify_attempts + 1 >= $4 THEN 'failed'::step_status
                ELSE 'pending'::step_status
            END,
            notify_attempts = notify_attempts + 1,
            notify_last_attempted_at = now(),
            notify_error = $3
        WHERE id = $1
        RETURNING notify_status, notify_attempts
    """,
    "ack": """
        UPDATE leads
        SET ack_status = CASE
                WHEN $2 = 'success' THEN 'success'::step_status
                WHEN $2 = 'permanent_failure' THEN 'failed'::step_status
                WHEN ack_attempts + 1 >= $4 THEN 'failed'::step_status
                ELSE 'pending'::step_status
            END,
            ack_attempts = ack_attempts + 1,
            ack_last_attempted_at = now(),
            ack_error = $3
        WHERE id = $1
        RETURNING ack_status, ack_attempts
    """,
}


async def record_step_attempt(
    pool: asyncpg.Pool, *, lead_id, step: str, result: StepResult, max_attempts: int
):
    query = _STEP_UPDATE_QUERIES[step]
    async with pool.acquire() as conn:
        if step == "crm":
            await conn.fetchrow(
                query, lead_id, result.outcome.value, result.error, max_attempts, result.external_id
            )
        else:
            await conn.fetchrow(query, lead_id, result.outcome.value, result.error, max_attempts)


# Backoff, computed once here in SQL rather than duplicated in Python (single source of
# truth): a step is eligible for retry if it's still 'pending', hasn't exceeded the
# attempt cap, and enough time has passed since its last attempt per
# min(base * 2^(attempts-1), cap) — exponential, capped, per ADR 0009.
_FETCH_ELIGIBLE_QUERIES = {
    step: f"""
        SELECT id, name, email, phone, message, source
        FROM leads
        WHERE {step}_status = 'pending'
          AND {step}_attempts < $1
          AND (
              {step}_attempts = 0
              OR {step}_last_attempted_at IS NULL
              OR {step}_last_attempted_at <= now() - (
                  LEAST($2 * POWER(2, {step}_attempts - 1), $3) * INTERVAL '1 second'
              )
          )
    """
    for step in ("crm", "notify", "ack")
}


async def fetch_eligible_for_retry(
    pool: asyncpg.Pool, *, step: str, max_attempts: int, base_seconds: int, cap_seconds: int
):
    query = _FETCH_ELIGIBLE_QUERIES[step]
    async with pool.acquire() as conn:
        return await conn.fetch(query, max_attempts, base_seconds, cap_seconds)
