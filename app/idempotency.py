import hashlib
import re
from datetime import datetime
from typing import Optional, Tuple


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _time_bucket(received_at: datetime, bucket_minutes: int) -> int:
    epoch_minutes = int(received_at.timestamp() // 60)
    return epoch_minutes // bucket_minutes


def derive_key(email: str, message: str, received_at: datetime, bucket_minutes: int) -> str:
    """Server-derived idempotency key (ADR 0008 fallback path).

    hash(normalized email + normalized message + time bucket). Two submissions from the
    same address with the same message content within the same bucket collapse into one
    lead; a different message, or the same message outside the bucket, is a new lead.
    """
    normalized = "|".join(
        [
            _normalize_email(email),
            _normalize_text(message),
            str(_time_bucket(received_at, bucket_minutes)),
        ]
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def resolve_idempotency_key(
    *,
    client_key: Optional[str],
    email: str,
    message: str,
    received_at: datetime,
    bucket_minutes: int,
) -> Tuple[str, str]:
    """Returns (idempotency_key, source) per ADR 0008: prefer the client-supplied key,
    fall back to the server-derived hash when the caller doesn't provide one."""
    if client_key and client_key.strip():
        return client_key.strip(), "client"
    return derive_key(email, message, received_at, bucket_minutes), "derived"
