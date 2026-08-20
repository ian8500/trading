from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.api.routes.ig_demo import shutdown_ig_runtime
from app.autopilot import autopilot_monitor
from app.core.config import get_settings


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Alembic owns schema creation and upgrades in every runtime environment.
    await autopilot_monitor.start()
    try:
        yield
    finally:
        await autopilot_monitor.stop()
        await shutdown_ig_runtime()


settings = get_settings()
app = FastAPI(title=settings.APP_NAME, version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-CSRF-Token"],
)
app.include_router(api_router, prefix="/api/v1")
