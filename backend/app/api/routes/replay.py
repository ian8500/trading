from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.auth.dependencies import csrf_admin
from app.auth.service import SessionIdentity
from app.backtesting.costs import CostPreset
from app.database.models import (
    AuditEventRecord,
    BacktestRecord,
    HistoricalBarRecord,
    InstrumentRecord,
    OpportunityRecord,
)
from app.database.session import get_db
from app.instruments.catalog import CORE_UNIVERSE, OFFICIAL_INTRADAY_SYMBOLS
from app.jobs.backtest_service import (
    DISPLAY_NAMES,
    BacktestRunRequest,
    execute_backtest,
    parse_boundary,
    serialize_opportunity,
)
from app.risk import RiskProfile

router = APIRouter(prefix="/replay", tags=["replay"])


class ReplayRequestBody(BaseModel):
    start: str
    end: str
    startingCapital: Decimal = Field(ge=Decimal("100"), le=Decimal("10000000"))
    strategy: Literal["Quant Baseline", "Quant Aggressive", "Regime Ensemble"]
    riskProfile: Literal["Conservative", "Standard", "Aggressive"]
    costModel: Literal["OPTIMISTIC", "REALISTIC", "STRESSED"]


def _latest(session: Session) -> BacktestRecord | None:
    return session.scalar(
        select(BacktestRecord)
        .where(BacktestRecord.status == "COMPLETED")
        .order_by(desc(BacktestRecord.completed_at), desc(BacktestRecord.created_at))
        .limit(1)
    )


def _build_replay(session: Session, record: BacktestRecord) -> dict[str, object]:
    result = record.result_payload
    private = result.get("_replay", {})
    equity_curve = private.get("equityCurve", result.get("equityCurve", []))
    symbols = list(record.configuration.get("symbols", []))
    checksums = result.get("dataChecksums", {})
    if not isinstance(checksums, dict):
        raise HTTPException(status_code=409, detail="backtest has no pinned data checksums")
    bars: dict[str, list[HistoricalBarRecord]] = {}
    for symbol in symbols:
        instrument = session.scalar(
            select(InstrumentRecord).where(InstrumentRecord.symbol == symbol)
        )
        if instrument is None:
            raise HTTPException(
                status_code=409, detail=f"pinned replay instrument is unavailable: {symbol}"
            )
        checksum = checksums.get(symbol)
        if not isinstance(checksum, str) or not checksum:
            raise HTTPException(
                status_code=409, detail=f"backtest has no pinned data checksum for {symbol}"
            )
        bars[symbol] = list(
            session.scalars(
                select(HistoricalBarRecord)
                .where(
                    HistoricalBarRecord.instrument_id == instrument.id,
                    HistoricalBarRecord.provider == "Yahoo Finance",
                    HistoricalBarRecord.interval == record.configuration["resolution"],
                    HistoricalBarRecord.complete.is_(True),
                    HistoricalBarRecord.manifest_checksum == checksum,
                    HistoricalBarRecord.timestamp
                    >= parse_boundary(record.configuration["date_from"]).replace(tzinfo=None),
                    HistoricalBarRecord.timestamp
                    < parse_boundary(record.configuration["date_to"]).replace(tzinfo=None),
                )
                .order_by(HistoricalBarRecord.timestamp)
            )
        )
        if not bars[symbol]:
            raise HTTPException(
                status_code=409,
                detail=f"pinned replay data revision is unavailable for {symbol}",
            )
    opportunities: dict[str, dict[str, object]] = {}
    opportunity_rows = session.scalars(
        select(OpportunityRecord)
        .where(OpportunityRecord.backtest_id == record.id)
        .order_by(
            OpportunityRecord.timestamp,
            desc(OpportunityRecord.expected_growth_score),
            OpportunityRecord.instrument,
        )
    )
    for row in opportunity_rows:
        # The UI currently has one decision-detail slot per replay tick. Pick
        # the deterministic top-ranked candidate rather than whichever row the
        # database happens to return last.
        opportunity_timestamp = row.timestamp.replace(tzinfo=UTC).isoformat()
        opportunities.setdefault(opportunity_timestamp, serialize_opportunity(row))
    indices = {symbol: 0 for symbol in bars}
    last_prices: dict[str, float] = {}
    ticks: list[dict[str, object]] = []
    for point in equity_curve:
        timestamp = parse_boundary(str(point["timestamp"]))
        for symbol, rows in bars.items():
            index = indices[symbol]
            while index < len(rows) and rows[index].timestamp.replace(tzinfo=UTC) <= timestamp:
                last_prices[DISPLAY_NAMES.get(symbol, symbol)] = float(rows[index].close)
                index += 1
            indices[symbol] = index
        opportunity = opportunities.get(timestamp.isoformat())
        tick: dict[str, object] = {
            "timestamp": timestamp.isoformat(),
            "prices": dict(last_prices),
            "regime": opportunity["regime"] if opportunity else "UNKNOWN",
            "managedEquity": float(point.get("equity", point.get("value", 0))),
            "unrealisedPnl": 0.0,
        }
        if opportunity:
            tick["opportunity"] = opportunity
        ticks.append(tick)
    if not ticks:
        raise HTTPException(status_code=409, detail="backtest has no replayable observations")
    return {
        "id": f"replay-{record.id}",
        "status": "READY",
        "dateFrom": record.configuration["date_from"],
        "dateTo": record.configuration["date_to"],
        "strategy": record.strategy,
        "riskProfile": record.configuration["risk_profile"],
        "costModel": record.configuration["cost_model"],
        "startingCapital": float(record.starting_equity),
        "ticks": ticks,
        "sourceBacktestId": record.id,
        "sameEventPath": True,
        "auditEventCount": len(private.get("auditTrail", [])),
    }


@router.get("/sessions/latest")
def latest_replay(db: Annotated[Session, Depends(get_db)]) -> dict[str, object]:
    record = _latest(db)
    if record is None:
        raise HTTPException(status_code=404, detail="run a backtest before opening replay")
    return _build_replay(db, record)


@router.post("/sessions")
def create_replay(
    body: ReplayRequestBody,
    identity: Annotated[SessionIdentity, Depends(csrf_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    start = parse_boundary(body.start)
    end = parse_boundary(body.end)
    available_symbols = tuple(
        symbol for symbol in OFFICIAL_INTRADAY_SYMBOLS if symbol in CORE_UNIVERSE
    )
    try:
        record = execute_backtest(
            db,
            BacktestRunRequest(
                name=f"Replay source · {body.strategy}",
                strategy=body.strategy,
                symbols=available_symbols,
                start=start,
                end=end,
                interval="1h",
                starting_equity=body.startingCapital,
                risk_profile=RiskProfile(body.riskProfile),
                cost_preset=CostPreset(body.costModel),
                maximum_holding_bars=25,
            ),
        )
    except (RuntimeError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    payload = _build_replay(db, record)
    db.add(
        AuditEventRecord(
            timestamp=datetime.now(UTC),
            category="CONTROL",
            severity="INFO",
            message="historical replay created",
            details={"backtest_id": record.id, "actor": identity.username},
        )
    )
    db.commit()
    return payload
