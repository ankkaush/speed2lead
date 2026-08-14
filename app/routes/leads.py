import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Header, Request

from app.config import settings
from app.idempotency import resolve_idempotency_key
from app.leads_repo import insert_or_get_lead
from app.schemas import LeadIn, LeadOut

logger = logging.getLogger("speed_to_lead")

router = APIRouter()


@router.post("/leads", response_model=LeadOut)
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

    row, duplicate = await insert_or_get_lead(
        request.app.state.db_pool,
        idempotency_key=key,
        idempotency_source=key_source,
        name=payload.name,
        email=payload.email,
        phone=payload.phone,
        message=payload.message,
        source=payload.source,
    )

    logger.info(
        f"lead_intake lead_id={row['id']} duplicate={duplicate} idempotency_source={key_source}"
    )

    return LeadOut(
        id=row["id"],
        duplicate=duplicate,
        crm_status=row["crm_status"],
        notify_status=row["notify_status"],
        ack_status=row["ack_status"],
        received_at=row["received_at"],
    )
