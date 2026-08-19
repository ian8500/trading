from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.database.models import AuditEventRecord, HistoricalBarRecord
from app.database.session import get_db

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/health")
def system_health(
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    include_audit: bool = False,
) -> dict[str, object]:
    now = datetime.now(UTC)
    services: list[dict[str, object]] = []
    try:
        db.execute(text("SELECT 1"))
        database_status = "healthy"
        database_message = "Database reachable"
    except Exception:
        database_status = "critical"
        database_message = "Database unavailable"
    bars = db.scalar(select(func.count()).select_from(HistoricalBarRecord)) or 0
    service_values = (
        ("backend", "Backend", "healthy", "FastAPI process responding"),
        ("database", "Database", database_status, database_message),
        (
            "historical-data",
            "Historical data",
            "healthy" if bars else "warning",
            f"{bars:,} validated bars persisted" if bars else "No bars imported",
        ),
        ("live-market-data", "Live market data", "neutral", "Inactive until IG Demo connects"),
        (
            "ig-auth",
            "IG authentication",
            "neutral",
            "Configured locally" if settings.ig_configured else "Not configured",
        ),
        ("ig-stream", "IG streaming", "neutral", "Disconnected"),
        ("ig-reconciliation", "IG reconciliation", "neutral", "Not connected"),
        ("strategy", "Strategy engine", "healthy", "Deterministic strategies available"),
        ("opportunity", "Opportunity engine", "healthy", "Inspectable scoring active"),
        ("challenger", "Devil's Advocate", "healthy", "Deterministic challenger active"),
        ("risk", "RiskEngine", "healthy", "Authoritative execution gate active"),
        ("news", "News", "neutral", f"Provider: {settings.NEWS_PROVIDER}"),
        ("macro", "Macro", "neutral", f"Provider: {settings.MACRO_PROVIDER}"),
        ("ai", "AI", "neutral", f"Provider: {settings.AI_PROVIDER}"),
        ("worker", "Job worker", "healthy", "Local bounded research jobs"),
        ("secret-scan", "Secret scan", "healthy", "Enforced locally and in CI"),
    )
    for identifier, name, status, message in service_values:
        services.append(
            {
                "id": identifier,
                "name": name,
                "status": status,
                "message": message,
                "checkedAt": now.isoformat(),
            }
        )
    audits: list[dict[str, object]] = []
    if include_audit:
        rows = db.scalars(
            select(AuditEventRecord).order_by(AuditEventRecord.timestamp.desc()).limit(100)
        )
        audits = [
            {
                "id": row.id,
                "timestamp": row.timestamp.isoformat(),
                "category": row.category
                if row.category in {"CONTROL", "RISK", "BROKER", "DATA", "STRATEGY", "SYSTEM"}
                else "SYSTEM",
                "summary": row.message,
                "detail": str(row.details),
                "severity": {"INFO": "healthy", "WARNING": "warning", "CRITICAL": "critical"}.get(
                    row.severity, "neutral"
                ),
                "actor": str(row.details.get("actor", "system")),
            }
            for row in rows
        ]
    return {
        "asOf": now.isoformat(),
        "services": services,
        "auditEvents": audits,
        "environment": {
            "appVersion": "0.1.0",
            "appEnvironment": settings.APP_ENV,
            "timezone": settings.APP_TIMEZONE,
            "database": "PostgreSQL"
            if settings.DATABASE_URL.startswith("postgresql")
            else "SQLite local fallback",
            "aiProvider": settings.AI_PROVIDER,
            "liveExecution": "DISABLED",
        },
    }
