import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.db import close_pool, init_pool
from app.logging_config import configure_logging
from app.routes.leads import router as leads_router

configure_logging()
logger = logging.getLogger("speed_to_lead")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"app_startup app_env={settings.app_env}")
    app.state.db_pool = await init_pool()
    logger.info("db_pool_ready")
    yield
    await close_pool()
    logger.info("app_shutdown")


app = FastAPI(title="Speed-to-Lead", lifespan=lifespan)
app.include_router(leads_router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "app_env": settings.app_env}
