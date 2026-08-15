import asyncio
import logging
from contextlib import asynccontextmanager

import sentry_sdk
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import settings
from app.correlation import correlation_id_middleware
from app.db import close_pool, init_pool
from app.http_client import close_http_client, init_http_client
from app.logging_config import configure_logging
from app.reconciliation import reconciliation_loop
from app.routes.leads import router as leads_router

configure_logging()
logger = logging.getLogger("speed_to_lead")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"app_startup app_env={settings.app_env}")

    # Initialized here, not at module import time (ADR 0011): settings.sentry_dsn is
    # read fresh on every app startup, which is what lets the test suite force it off
    # via monkeypatch before the lifespan runs -- an import-time sentry_sdk.init() would
    # already have fired using whatever was in .env at process start, before any test
    # got a chance to override it.
    if settings.sentry_dsn:
        sentry_sdk.init(dsn=settings.sentry_dsn, environment=settings.app_env)
        logger.info("sentry_active=true")
    else:
        logger.info("sentry_active=false")

    app.state.db_pool = await init_pool()
    app.state.http_client = await init_http_client()
    logger.info("db_pool_ready")

    reconciliation_task = asyncio.create_task(
        reconciliation_loop(
            app.state.db_pool,
            app.state.http_client,
            interval_seconds=settings.reconciliation_interval_seconds,
            max_attempts=settings.max_step_attempts,
            base_seconds=settings.backoff_base_seconds,
            cap_seconds=settings.backoff_cap_seconds,
        )
    )
    logger.info(f"reconciliation_loop_started interval_seconds={settings.reconciliation_interval_seconds}")

    yield

    reconciliation_task.cancel()
    try:
        await reconciliation_task
    except asyncio.CancelledError:
        pass
    await close_http_client()
    await close_pool()
    logger.info("app_shutdown")


app = FastAPI(title="Speed-to-Lead", lifespan=lifespan)
app.middleware("http")(correlation_id_middleware)
app.include_router(leads_router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Safety net (ADR 0010): catches anything not already handled by a more specific
    handler (FastAPI/Starlette keep their own handling of HTTPException and validation
    errors, so 401/422/429/503 etc. are unaffected by this and still return their normal
    bodies). Two things this fixes at once: no internal detail (a stack trace, an
    exception message that might contain a fragment of a DB query or a provider's
    response) ever reaches the caller, and — unlike an unhandled exception falling
    through to Starlette's default behavior — this one *does* go through our structured
    JSON logger, so it looks like every other log line an operator has to read.

    sentry_sdk.capture_exception is called explicitly here (ADR 0011), not left to
    Sentry's automatic instrumentation: because this handler already catches and
    responds to the exception, it never propagates further up the stack, which is
    exactly the signal Sentry's auto-capture relies on to notice something went wrong.
    """
    sentry_sdk.capture_exception(exc)
    logger.exception(f"unhandled_exception path={request.url.path}")
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/health")
async def health(request: Request) -> JSONResponse:
    """Verifies the database is actually reachable (ADR 0011) rather than always
    returning "ok" -- this is what makes Render's deploy health-check gating (ADR 0006)
    meaningful instead of a rubber stamp."""
    try:
        async with request.app.state.db_pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
    except Exception as exc:
        sentry_sdk.capture_exception(exc)
        logger.exception("health_check_db_unreachable")
        return JSONResponse(status_code=503, content={"status": "error", "detail": "database unreachable"})

    return JSONResponse(status_code=200, content={"status": "ok", "app_env": settings.app_env})
