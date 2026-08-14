import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.logging_config import configure_logging

configure_logging()
logger = logging.getLogger("speed_to_lead")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"app_startup app_env={settings.app_env}")
    yield


app = FastAPI(title="Speed-to-Lead", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "app_env": settings.app_env}
