import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import settings
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
    """
    logger.exception(f"unhandled_exception path={request.url.path}")
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "app_env": settings.app_env}
