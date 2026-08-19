from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.auth.dependencies import csrf_admin
from app.auth.service import SessionIdentity
from app.database.models import AuditEventRecord, BacktestRecord
from app.database.session import get_db
from app.database.state import read_state, write_state
from app.risk import RiskProfile, limits_for_profile

router = APIRouter(prefix="/risk", tags=["risk"])


class RiskProfileUpdate(BaseModel):
    profile: Literal["Conservative", "Standard", "Aggressive", "Experimental", "Custom"]
    taperEnabled: bool = False


def _latest_equity(session: Session) -> Decimal:
    latest = session.scalar(
        select(BacktestRecord)
        .where(BacktestRecord.status == "COMPLETED")
        .order_by(desc(BacktestRecord.completed_at))
        .limit(1)
    )
    return latest.final_equity if latest and latest.final_equity is not None else Decimal("500")


@router.get("/status")
def risk_status(db: Annotated[Session, Depends(get_db)]) -> dict[str, object]:
    state = read_state(db, "risk_profile", {"profile": "Standard", "taperEnabled": False})
    profile = RiskProfile(state["profile"])
    limits = (
        limits_for_profile(profile)
        if profile is not RiskProfile.CUSTOM
        else limits_for_profile("Standard")
    )
    equity = _latest_equity(db)
    return {
        "profile": profile.value,
        "managedEquity": float(equity),
        "riskPerTrade": float(limits.risk_per_trade),
        "maxOpenRisk": float(limits.max_open_risk),
        "currentOpenRisk": 0.0,
        "marginUsage": 0.0,
        "effectiveLeverage": 0.0,
        "dailyPnl": 0.0,
        "weeklyPnl": 0.0,
        "drawdown": 0.0,
        "taperEnabled": bool(state.get("taperEnabled", False)),
        "circuitBreakers": [
            {
                "name": "Execution gate",
                "status": "healthy",
                "threshold": "all checks pass",
                "current": "closed to Live",
                "detail": "V1 Live execution is compiled out; Demo starts stopped.",
            }
        ],
        "correlationExposure": [],
        "blockedStrategies": [],
        "blockedMarkets": [],
    }


@router.post("/profile")
def update_risk_profile(
    payload: RiskProfileUpdate,
    identity: Annotated[SessionIdentity, Depends(csrf_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    if payload.profile == "Custom":
        # V1 does not accept unbounded arbitrary limits through this convenience endpoint.
        raise HTTPException(
            status_code=422,
            detail="Custom risk requires an explicit validated server configuration",
        )
    value = write_state(
        db,
        "risk_profile",
        {"profile": payload.profile, "taperEnabled": payload.taperEnabled},
    )
    db.add(
        AuditEventRecord(
            timestamp=datetime.now(UTC),
            category="CONTROL",
            severity="INFO",
            message="risk profile updated",
            details={
                "profile": payload.profile,
                "taper": payload.taperEnabled,
                "actor": identity.username,
            },
        )
    )
    db.commit()
    return value
