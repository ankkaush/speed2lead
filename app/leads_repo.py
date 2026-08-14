import asyncpg

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
