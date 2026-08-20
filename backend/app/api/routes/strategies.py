from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import csrf_admin
from app.auth.service import SessionIdentity
from app.database.models import BacktestRecord
from app.database.session import get_db

router = APIRouter(prefix="/strategies", tags=["strategies"])


@router.get("/versions")
def strategy_versions(
    db: Annotated[Session, Depends(get_db)], include_metrics: bool = True
) -> list[dict[str, object]]:
    del include_metrics
    records = list(db.scalars(select(BacktestRecord).where(BacktestRecord.status == "COMPLETED")))
    latest = {record.strategy: record for record in records}
    definitions = (
        (
            "quant-baseline-v1",
            "Quant Baseline",
            "1.0.0",
            "CHAMPION",
            "Trend and Breakout",
            "Quant Baseline",
        ),
        (
            "quant-aggressive-v1",
            "Quant Aggressive",
            "1.0.0",
            "CHALLENGER",
            "Trend and Breakout",
            "Quant Aggressive",
        ),
        (
            "regime-ensemble-v1",
            "Regime Ensemble",
            "1.0.0",
            "CHALLENGER",
            "Regime Switching",
            "Regime Ensemble",
        ),
    )
    result: list[dict[str, object]] = []
    for identifier, name, version, role, family, key in definitions:
        record = latest.get(key)
        metrics = record.metrics if record else {}
        result.append(
            {
                "id": identifier,
                "name": name,
                "version": version,
                "role": role,
                "family": family,
                "state": "NORMAL",
                "createdAt": (record.created_at if record else datetime.now(UTC)).isoformat(),
                "immutable": True,
                "parameters": record.configuration if record else {},
                "dataRange": str(
                    (record.configuration if record else {}).get("date_range", "Not run")
                ),
                "historical": {
                    "returnPercent": float(metrics.get("total_return", 0)),
                    "sharpe": float(metrics.get("sharpe", 0) or 0),
                    "drawdown": float(metrics.get("maximum_drawdown", 0)),
                    "trades": int(metrics.get("number_of_trades", 0)),
                },
                "outOfSample": {"returnPercent": 0, "sharpe": 0, "degradation": 0},
                "demo": {"returnPercent": 0, "trades": 0, "durationDays": 0},
                # A registry role is not promotion evidence. The frozen protocol currently
                # marks every strategy NOT_ELIGIBLE.
                "promotionState": "NOT_ELIGIBLE",
                "parameterSurface": [],
            }
        )
    return result


@router.post("/{strategy_id}/promote")
def promote_strategy(
    strategy_id: str,
    identity: Annotated[SessionIdentity, Depends(csrf_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    del strategy_id, identity, db
    raise HTTPException(
        status_code=409,
        detail=(
            "Promotion blocked: historical, walk-forward, robustness, and forward Demo "
            "evidence are required"
        ),
    )
