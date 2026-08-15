import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import asyncpg
from fastapi import APIRouter, Depends, Header, HTTPException, Request

from app.config import settings
from app.idempotency import resolve_idempotency_key
from app.leads_repo import get_lead_status, insert_or_get_lead
from app.pipeline import attempt_all_steps
from app.rate_limit import check_rate_limit
from app.schemas import LeadIn, LeadOut
from app.security import verify_webhook_signature

logger = logging.getLogger("speed_to_lead")

router = APIRouter()


@router.post(
    "/leads",
    response_model=LeadOut,
    # Rate limit first (cheap, rejects floods before doing any crypto work), then the
    # signature check (ADR 0010) -- both run before the route body, before we've spent
    # any DB or downstream-API effort on a request that shouldn't be trusted.
    dependencies=[Depends(check_rate_limit), Depends(verify_webhook_signature)],
)
async def create_lead(
    payload: LeadIn,
    request: Request,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
) -> LeadOut:
    received_at = datetime.now(timezone.utc)

    key, key_source = resolve_idempotency_key(
        client_key=idempotency_key,
        email=payload.email,
        message=payload.message,
        received_at=received_at,
        bucket_minutes=settings.idempotency_bucket_minutes,
    )

    pool = request.app.state.db_pool

    try:
        row, duplicate = await insert_or_get_lead(
            pool,
            idempotency_key=key,
            idempotency_source=key_source,
            name=payload.name,
            email=payload.email,
            phone=payload.phone,
            message=payload.message,
            source=payload.source,
        )
    except (asyncpg.PostgresConnectionError, asyncio.TimeoutError, OSError) as exc:
        logger.error(f"lead_intake_db_unavailable error={exc!r}")
        raise HTTPException(status_code=503, detail="Temporarily unavailable, please retry") from exc

    logger.info(
        f"lead_intake lead_id={row['id']} duplicate={duplicate} idempotency_source={key_source}"
    )

    if not duplicate:
        # Persist-then-process (ADR 0008): the row above is already committed before any
        # downstream call is attempted, so a crash here leaves a recoverable 'pending'
        # row for the reconciliation sweep to pick up, not a lost lead.
        lead_for_pipeline = {
            "id": row["id"],
            "name": payload.name,
            "email": payload.email,
            "phone": payload.phone,
            "message": payload.message,
            "source": payload.source,
        }
        await attempt_all_steps(pool, request.app.state.http_client, lead_for_pipeline, settings.max_step_attempts)
        row = await get_lead_status(pool, row["id"])
    # Duplicates are not reprocessed here (ADR 0008): the intake endpoint stays
    # single-purpose (accept + dedupe); resuming a stuck row is the reconciliation
    # sweep's job, not the request path's.

    return LeadOut(
        id=row["id"],
        duplicate=duplicate,
        crm_status=row["crm_status"],
        notify_status=row["notify_status"],
        ack_status=row["ack_status"],
        received_at=row["received_at"],
    )
