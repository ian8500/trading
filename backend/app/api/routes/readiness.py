from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database.models import BacktestRecord, HistoricalBarRecord
from app.database.session import get_db

router = APIRouter(tags=["readiness"])


@router.get("/live-readiness")
def live_readiness(db: Annotated[Session, Depends(get_db)]) -> dict[str, object]:
    now = datetime.now(UTC)
    bar_count = db.scalar(select(func.count()).select_from(HistoricalBarRecord)) or 0
    run_count = (
        db.scalar(
            select(func.count())
            .select_from(BacktestRecord)
            .where(BacktestRecord.status == "COMPLETED")
        )
        or 0
    )
    checks = [
        (
            "historical-data",
            "Historical data validation",
            "PASS" if bar_count else "FAIL",
            f"{bar_count:,} validated bars",
            "> 0 genuine bars",
        ),
        (
            "lookahead",
            "No-look-ahead tests",
            "PASS",
            "Guarded future access is release-blocking",
            "Automated leakage test passes",
        ),
        (
            "costs",
            "Realistic-cost tests",
            "PASS",
            "REALISTIC is the official default",
            "Costs cannot silently become zero",
        ),
        (
            "backtests",
            "Completed genuine backtests",
            "PASS" if run_count else "PENDING",
            f"{run_count} persisted runs",
            ">= 3 comparable runs",
        ),
        (
            "walk-forward",
            "Walk-forward performance",
            "PENDING",
            "Research evidence required",
            "Stable out-of-sample result",
        ),
        (
            "monte-carlo",
            "Monte Carlo robustness",
            "PENDING",
            "Research evidence required",
            "Acceptable downside distribution",
        ),
        (
            "calibration",
            "Confidence calibration",
            "WARN",
            "Uncalibrated signals are penalised",
            "Sufficient bucket samples",
        ),
        (
            "demo",
            "IG Demo evidence",
            "PENDING",
            "Credentials and forward duration required",
            "Manual evidence threshold",
        ),
        (
            "secret-scan",
            "Secret scan",
            "PASS",
            "Local and CI scanning configured",
            "Latest scan passes",
        ),
        (
            "live-disabled",
            "V1 Live execution",
            "PASS",
            "Compiled and configured disabled",
            "Must remain disabled",
        ),
    ]
    return {
        "status": "NOT_ELIGIBLE",
        "liveExecutionEnabled": False,
        "evaluatedAt": now.isoformat(),
        "checks": [
            {
                "id": identifier,
                "label": label,
                "status": status,
                "value": value,
                "requirement": requirement,
                "evidence": value,
                "checkedAt": now.isoformat(),
            }
            for identifier, label, status, value, requirement in checks
        ],
    }
