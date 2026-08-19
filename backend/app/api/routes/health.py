from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.database.session import get_db

router = APIRouter(tags=["system"])


@router.get("/health")
def health(response: Response, db: Annotated[Session, Depends(get_db)]) -> dict[str, Any]:
    database = "healthy"
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        database = "unhealthy"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "healthy" if database == "healthy" else "degraded",
        "timestamp": datetime.now(UTC).isoformat(),
        "database": database,
        "mode": "HISTORICAL",
    }


@router.get("/config/public")
def public_config(settings: Annotated[Settings, Depends(get_settings)]) -> dict[str, Any]:
    return {
        "app_name": settings.APP_NAME,
        "timezone": settings.APP_TIMEZONE,
        "base_currency": settings.APP_BASE_CURRENCY,
        "initial_managed_capital": str(settings.INITIAL_MANAGED_CAPITAL_GBP),
        "target_capital": str(settings.TARGET_CAPITAL_GBP),
        "ig_environment": "DEMO",
        "ig_configured": settings.ig_configured,
        "autonomous_demo_enabled": settings.AUTONOMOUS_DEMO_ENABLED,
        "live_execution_enabled": False,
        "ai_provider": settings.AI_PROVIDER,
    }
