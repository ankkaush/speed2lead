import uuid
from datetime import datetime, timedelta, timezone

from app.adapters.base import StepOutcome, StepResult
from app.leads_repo import fetch_eligible_for_retry, record_step_attempt
from tests.conftest import TEST_EMAIL_DOMAIN, TEST_EMAIL_LOCAL_PREFIX

MAX_ATTEMPTS = 5
BASE_SECONDS = 60
CAP_SECONDS = 3600


async def _insert_lead(pool, *, crm_status="pending", crm_attempts=0, crm_last_attempted_at=None):
    key = f"reconciliation-test-{uuid.uuid4()}"
    email = f"{TEST_EMAIL_LOCAL_PREFIX}reconciliation-{uuid.uuid4().hex[:8]}@{TEST_EMAIL_DOMAIN}"
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO leads (
                idempotency_key, idempotency_source, name, email, message,
                crm_status, crm_attempts, crm_last_attempted_at
            )
            VALUES ($1, 'client', 'Test', $2, 'hello', $3, $4, $5)
            RETURNING id
            """,
            key,
            email,
            crm_status,
            crm_attempts,
            crm_last_attempted_at,
        )
        return row["id"]


async def _cleanup(pool, lead_id):
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM leads WHERE id = $1", lead_id)


async def _eligible_ids(pool):
    rows = await fetch_eligible_for_retry(
        pool, step="crm", max_attempts=MAX_ATTEMPTS, base_seconds=BASE_SECONDS, cap_seconds=CAP_SECONDS
    )
    return {row["id"] for row in rows}


async def test_never_attempted_row_is_eligible(db_pool):
    lead_id = await _insert_lead(db_pool, crm_attempts=0, crm_last_attempted_at=None)
    try:
        assert lead_id in await _eligible_ids(db_pool)
    finally:
        await _cleanup(db_pool, lead_id)


async def test_row_not_yet_eligible_before_backoff_elapses(db_pool):
    lead_id = await _insert_lead(
        db_pool, crm_attempts=1, crm_last_attempted_at=datetime.now(timezone.utc)
    )
    try:
        assert lead_id not in await _eligible_ids(db_pool)
    finally:
        await _cleanup(db_pool, lead_id)


async def test_row_eligible_once_backoff_elapses(db_pool):
    lead_id = await _insert_lead(
        db_pool,
        crm_attempts=1,
        crm_last_attempted_at=datetime.now(timezone.utc) - timedelta(minutes=5),
    )
    try:
        assert lead_id in await _eligible_ids(db_pool)
    finally:
        await _cleanup(db_pool, lead_id)


async def test_row_at_attempt_cap_is_not_eligible(db_pool):
    lead_id = await _insert_lead(
        db_pool,
        crm_attempts=MAX_ATTEMPTS,
        crm_last_attempted_at=datetime.now(timezone.utc) - timedelta(hours=2),
    )
    try:
        assert lead_id not in await _eligible_ids(db_pool)
    finally:
        await _cleanup(db_pool, lead_id)


async def test_non_pending_row_is_not_eligible(db_pool):
    lead_id = await _insert_lead(
        db_pool,
        crm_status="success",
        crm_attempts=1,
        crm_last_attempted_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    try:
        assert lead_id not in await _eligible_ids(db_pool)
    finally:
        await _cleanup(db_pool, lead_id)


async def _crm_status_and_attempts(pool, lead_id):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT crm_status, crm_attempts FROM leads WHERE id = $1", lead_id)
        return row["crm_status"], row["crm_attempts"]


async def test_record_success_sets_status_and_external_id(db_pool):
    lead_id = await _insert_lead(db_pool)
    try:
        await record_step_attempt(
            db_pool,
            lead_id=lead_id,
            step="crm",
            result=StepResult(outcome=StepOutcome.SUCCESS, external_id="hubspot-123"),
            max_attempts=MAX_ATTEMPTS,
        )
        status, attempts = await _crm_status_and_attempts(db_pool, lead_id)
        assert status == "success"
        assert attempts == 1
    finally:
        await _cleanup(db_pool, lead_id)


async def test_record_permanent_failure_sets_failed_immediately(db_pool):
    lead_id = await _insert_lead(db_pool)
    try:
        await record_step_attempt(
            db_pool,
            lead_id=lead_id,
            step="crm",
            result=StepResult(outcome=StepOutcome.PERMANENT_FAILURE, error="bad token"),
            max_attempts=MAX_ATTEMPTS,
        )
        status, attempts = await _crm_status_and_attempts(db_pool, lead_id)
        assert status == "failed"
        assert attempts == 1
    finally:
        await _cleanup(db_pool, lead_id)


async def test_record_transient_failure_stays_pending_below_cap(db_pool):
    lead_id = await _insert_lead(db_pool)
    try:
        await record_step_attempt(
            db_pool,
            lead_id=lead_id,
            step="crm",
            result=StepResult(outcome=StepOutcome.TRANSIENT_FAILURE, error="timeout"),
            max_attempts=MAX_ATTEMPTS,
        )
        status, attempts = await _crm_status_and_attempts(db_pool, lead_id)
        assert status == "pending"
        assert attempts == 1
    finally:
        await _cleanup(db_pool, lead_id)


async def test_record_transient_failure_at_cap_sets_failed(db_pool):
    lead_id = await _insert_lead(db_pool, crm_attempts=MAX_ATTEMPTS - 1)
    try:
        await record_step_attempt(
            db_pool,
            lead_id=lead_id,
            step="crm",
            result=StepResult(outcome=StepOutcome.TRANSIENT_FAILURE, error="timeout"),
            max_attempts=MAX_ATTEMPTS,
        )
        status, attempts = await _crm_status_and_attempts(db_pool, lead_id)
        assert status == "failed"
        assert attempts == MAX_ATTEMPTS
    finally:
        await _cleanup(db_pool, lead_id)
