import uuid
from contextvars import ContextVar
from typing import Optional

# A per-request ID, readable from anywhere in the code during that request without
# threading it through every function call (ADR 0011). Set once per request by the
# middleware below; read by the log formatter (app/logging_config.py) so every log line
# emitted while handling a request carries it automatically.
correlation_id_var: ContextVar[Optional[str]] = ContextVar("correlation_id", default=None)


class CorrelationIdMiddleware:
    """Pure ASGI middleware, deliberately NOT the `@app.middleware("http")` /
    BaseHTTPMiddleware style (ADR 0012, found via a Phase 7 failure-injection test):
    BaseHTTPMiddleware has a documented Starlette interaction bug where an exception
    raised inside a route can escape past a registered `@app.exception_handler(Exception)`
    instead of being caught by it, because BaseHTTPMiddleware re-raises the exception
    after it's already past the layer that would normally route it to our handler. A
    plain ASGI middleware (implementing __call__(scope, receive, send) directly) doesn't
    have this problem -- it sits at a layer where FastAPI's own exception handling still
    applies normally.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        incoming = headers.get(b"x-request-id")
        correlation_id = incoming.decode("utf-8") if incoming else str(uuid.uuid4())

        token = correlation_id_var.set(correlation_id)

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                response_headers = list(message.get("headers", []))
                response_headers.append((b"x-request-id", correlation_id.encode("utf-8")))
                message["headers"] = response_headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            correlation_id_var.reset(token)
