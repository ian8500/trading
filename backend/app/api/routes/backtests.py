from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.auth.dependencies import csrf_admin
from app.auth.service import SessionIdentity
from app.backtesting.costs import CostPreset
from app.database.models import AuditEventRecord, BacktestRecord
from app.database.session import get_db
from app.jobs.backtest_service import (
    BacktestRunRequest,
    canonical_symbol,
    execute_backtest,
    parse_boundary,
)
from app.risk import RiskProfile

router = APIRouter(prefix="/backtests", tags=["backtests"])


class BacktestRequestBody(BaseModel):
    dateFrom: str
    dateTo: str
    startingCapital: Decimal = Field(ge=Decimal("100"), le=Decimal("10000000"))
    instruments: list[str] = Field(min_length=1, max_length=25)
    strategies: list[str] = Field(min_length=1, max_length=3)
    riskProfile: Literal["Conservative", "Standard", "Aggressive", "Experimental"]
    costModel: Literal["OPTIMISTIC", "REALISTIC", "STRESSED"]
    resolution: Literal["1d", "1h"]
    compounding: bool = True
    riskTaper: bool = False


def _public_payload(record: BacktestRecord) -> dict[str, object]:
    return {key: value for key, value in record.result_payload.items() if not key.startswith("_")}


@router.get("")
def list_backtests(
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[dict[str, object]]:
    records = db.scalars(
        select(BacktestRecord)
        .where(BacktestRecord.status == "COMPLETED")
        .order_by(desc(BacktestRecord.completed_at), desc(BacktestRecord.created_at))
        .limit(limit)
    )
    return [_public_payload(record) for record in records if record.result_payload]


@router.get("/{backtest_id}")
def get_backtest(backtest_id: str, db: Annotated[Session, Depends(get_db)]) -> dict[str, object]:
    record = db.get(BacktestRecord, backtest_id)
    if record is None or not record.result_payload:
        raise HTTPException(status_code=404, detail="backtest not found")
    return _public_payload(record)


@router.post("")
def run_backtest(
    body: BacktestRequestBody,
    identity: Annotated[SessionIdentity, Depends(csrf_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    if not body.compounding:
        raise HTTPException(
            status_code=422,
            detail="this first-pass engine requires managed-equity compounding to remain enabled",
        )
    if len(body.strategies) != 1:
        raise HTTPException(
            status_code=422,
            detail="run one strategy per job, then compare completed runs side by side",
        )
    try:
        request = BacktestRunRequest(
            name=f"{body.strategies[0]} · {body.resolution} · {body.costModel.lower()} costs",
            strategy=body.strategies[0],
            symbols=tuple(canonical_symbol(value) for value in body.instruments),
            start=parse_boundary(body.dateFrom),
            end=parse_boundary(body.dateTo, end=True),
            interval=body.resolution,
            starting_equity=body.startingCapital,
            risk_profile=RiskProfile(body.riskProfile),
            cost_preset=CostPreset(body.costModel),
            maximum_holding_bars=2 if body.resolution == "1d" else 25,
            risk_taper=body.riskTaper,
        )
        record = execute_backtest(db, request)
    except (RuntimeError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.add(
        AuditEventRecord(
            timestamp=datetime.now(UTC),
            category="CONTROL",
            severity="INFO",
            message="historical backtest requested",
            details={"backtest_id": record.id, "actor": identity.username},
        )
    )
    db.commit()
    return _public_payload(record)


@router.post("/{backtest_id}/cancel")
def cancel_backtest(
    backtest_id: str,
    identity: Annotated[SessionIdentity, Depends(csrf_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, str]:
    record = db.get(BacktestRecord, backtest_id)
    if record is None:
        raise HTTPException(status_code=404, detail="backtest not found")
    if record.status != "RUNNING":
        raise HTTPException(status_code=409, detail="backtest is not running")
    record.status = "CANCELLED"
    db.add(
        AuditEventRecord(
            timestamp=datetime.now(UTC),
            category="CONTROL",
            severity="WARNING",
            message="historical backtest cancelled",
            details={"backtest_id": record.id, "actor": identity.username},
        )
    )
    db.commit()
    return {"id": record.id, "status": record.status}
