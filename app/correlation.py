import uuid
from contextvars import ContextVar
from typing import Optional

# A per-request ID, readable from anywhere in the code during that request without
# threading it through every function call (ADR 0011). Set once per request by the
# middleware below; read by the log formatter (app/logging_config.py) so every log line
# emitted while handling a request carries it automatically.
correlation_id_var: ContextVar[Optional[str]] = ContextVar("correlation_id", default=None)


async def correlation_id_middleware(request, call_next):
    """If the caller already has a request ID (their own tracing), reuse it -- their
    logs and ours can then be cross-referenced directly. Otherwise generate one. Echoed
    back in the response header either way, so a caller always knows the ID to quote
    when reporting an issue."""
    incoming_id = request.headers.get("X-Request-ID")
    correlation_id = incoming_id if incoming_id else str(uuid.uuid4())

    token = correlation_id_var.set(correlation_id)
    try:
        response = await call_next(request)
    finally:
        correlation_id_var.reset(token)

    response.headers["X-Request-ID"] = correlation_id
    return response
