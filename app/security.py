import hashlib
import hmac
import logging
from typing import Optional

from fastapi import Header, HTTPException, Request

from app.config import settings

logger = logging.getLogger("speed_to_lead")


async def verify_webhook_signature(
    request: Request,
    x_webhook_signature: Optional[str] = Header(default=None, alias="X-Webhook-Signature"),
) -> None:
    """Server-to-server auth for POST /leads (ADR 0010): the caller computes
    HMAC-SHA256(shared secret, raw request body) and sends it as a header; we recompute
    it ourselves and compare. This only works because the caller is a server that can
    keep the secret secret — a browser calling us directly could never do this safely,
    since anything in client-side JS is visible to anyone who opens dev tools.

    hmac.compare_digest (not ==) is deliberate: a plain string comparison exits early on
    the first mismatched byte, and an attacker measuring response times could use that to
    guess the correct signature one byte at a time. compare_digest always takes the same
    time regardless of where strings differ.
    """
    if not x_webhook_signature:
        logger.warning(f"webhook_signature_missing path={request.url.path}")
        raise HTTPException(status_code=401, detail="Missing signature")

    body = await request.body()
    expected_signature = hmac.new(
        settings.webhook_signing_secret.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected_signature, x_webhook_signature):
        logger.warning(f"webhook_signature_invalid path={request.url.path}")
        raise HTTPException(status_code=401, detail="Invalid signature")
