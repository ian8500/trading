from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.database.models import BacktestRecord, OpportunityRecord
from app.database.session import get_db
from app.jobs.backtest_service import serialize_opportunity

router = APIRouter(tags=["portfolio"])


def _latest(session: Session) -> BacktestRecord | None:
    return session.scalar(
        select(BacktestRecord)
        .where(BacktestRecord.status == "COMPLETED")
        .order_by(desc(BacktestRecord.completed_at), desc(BacktestRecord.created_at))
        .limit(1)
    )


def _services(now: datetime) -> list[dict[str, object]]:
    return [
        {
            "id": identifier,
            "name": name,
            "status": status,
            "message": message,
            "checkedAt": now.isoformat(),
        }
        for identifier, name, status, message in (
            ("research", "Historical research", "healthy", "Completed-bar engine ready"),
            ("risk", "RiskEngine", "healthy", "Mandatory gate active"),
            ("challenger", "Challenger", "healthy", "Deterministic review active"),
            ("ig-demo", "IG Demo", "neutral", "Stopped by default"),
            ("live", "Live execution", "healthy", "Hard-disabled in V1"),
        )
    ]


def _strategy_health(session: Session) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for name in ("Quant Baseline", "Quant Aggressive", "Regime Ensemble"):
        record = session.scalar(
            select(BacktestRecord)
            .where(BacktestRecord.strategy == name, BacktestRecord.status == "COMPLETED")
            .order_by(desc(BacktestRecord.completed_at))
            .limit(1)
        )
        metrics = record.metrics if record else {}
        output.append(
            {
                "id": name.lower().replace(" ", "-"),
                "name": name,
                "state": "NORMAL" if record else "OBSERVATION_ONLY",
                "expectancy": float(metrics.get("expectancy", 0)),
                "winRate": float(Decimal(str(metrics.get("win_rate", 0))) * 100),
                "profitFactor": float(metrics.get("profit_factor", 0) or 0),
                "drawdown": float(Decimal(str(metrics.get("maximum_drawdown", 0))) * 100),
                "sampleSize": int(metrics.get("number_of_trades", 0)),
                "updatedAt": (
                    (record.completed_at or record.created_at).replace(tzinfo=UTC).isoformat()
                    if record
                    else datetime.now(UTC).isoformat()
                ),
            }
        )
    return output


def _dashboard(session: Session, settings: Settings) -> dict[str, object]:
    now = datetime.now(UTC)
    latest = _latest(session)
    if latest and latest.result_payload:
        result = latest.result_payload
        metrics = result["metrics"]
        opportunity_rows = session.scalars(
            select(OpportunityRecord)
            .where(OpportunityRecord.backtest_id == latest.id)
            .order_by(
                desc(OpportunityRecord.timestamp), desc(OpportunityRecord.expected_growth_score)
            )
            .limit(100)
        )
        opportunities = [serialize_opportunity(row) for row in opportunity_rows]
        starting = float(metrics["startingEquity"])
        equity = float(metrics["finalEquity"])
        return {
            "asOf": str(result.get("completedAt", now.isoformat())),
            "mode": "HISTORICAL",
            "startingCapital": starting,
            "managedEquity": equity,
            "brokerDemoBalance": None,
            "returnPercent": float(metrics["totalReturn"]),
            "target": float(settings.TARGET_CAPITAL_GBP),
            "maxDrawdown": float(metrics["maximumDrawdown"]),
            "openRisk": 0.0,
            "autonomousDemo": False,
            "circuitBreakers": "HEALTHY",
            "equityCurve": result["equityCurve"],
            "drawdownCurve": result["drawdownCurve"],
            "exposureCurve": result["exposureCurve"],
            "opportunities": [item for item in opportunities if item["status"] == "ELIGIBLE"],
            "positions": [],
            "recentTrades": list(reversed(result["trades"][-100:])),
            "rejectedOpportunities": [
                item for item in opportunities if item["status"] != "ELIGIBLE"
            ],
            "strategyHealth": _strategy_health(session),
            "events": [],
            "services": _services(now),
        }
    starting = float(settings.INITIAL_MANAGED_CAPITAL_GBP)
    return {
        "asOf": now.isoformat(),
        "mode": "HISTORICAL",
        "startingCapital": starting,
        "managedEquity": starting,
        "brokerDemoBalance": None,
        "returnPercent": 0.0,
        "target": float(settings.TARGET_CAPITAL_GBP),
        "maxDrawdown": 0.0,
        "openRisk": 0.0,
        "autonomousDemo": False,
        "circuitBreakers": "HEALTHY",
        "equityCurve": [{"timestamp": now.isoformat(), "value": starting}],
        "drawdownCurve": [{"timestamp": now.isoformat(), "value": 0}],
        "exposureCurve": [{"timestamp": now.isoformat(), "value": 0}],
        "opportunities": [],
        "positions": [],
        "recentTrades": [],
        "rejectedOpportunities": [],
        "strategyHealth": _strategy_health(session),
        "events": [],
        "services": _services(now),
    }


@router.get("/opportunities")
def opportunities(
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    include_rejected: bool = True,
) -> list[dict[str, object]]:
    latest = _latest(db)
    if latest is None:
        return []
    query = select(OpportunityRecord).where(OpportunityRecord.backtest_id == latest.id)
    if not include_rejected:
        query = query.where(OpportunityRecord.approved.is_(True))
    rows = db.scalars(
        query.order_by(
            desc(OpportunityRecord.timestamp), desc(OpportunityRecord.expected_growth_score)
        ).limit(limit)
    )
    return [serialize_opportunity(row) for row in rows]


@router.get("/dashboard/overview")
def dashboard_overview(
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, object]:
    return _dashboard(db, settings)


@router.get("/positions")
def positions(
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    include_closed: bool = True,
) -> dict[str, object]:
    del include_closed
    return _dashboard(db, settings)
