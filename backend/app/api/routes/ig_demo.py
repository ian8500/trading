from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.auth.dependencies import csrf_admin
from app.auth.service import SessionIdentity
from app.brokers.base import AccountSnapshot, BrokerPosition
from app.brokers.ig import IGCredentials, IGDemoBroker
from app.brokers.ig.errors import IGError
from app.brokers.ig.orders import IntentStatus
from app.brokers.ig.safety import DemoSafetyState, PersistentDemoSafetyService
from app.core.config import Settings, get_settings
from app.database.models import AuditEventRecord, BacktestRecord
from app.database.session import get_db

router = APIRouter(prefix="/ig-demo", tags=["ig-demo"])
_STATE_PATH = Path("data/ig-demo/state.sqlite3")


@dataclass(slots=True)
class _Runtime:
    broker: IGDemoBroker | None = None
    connected: bool = False
    account: AccountSnapshot | None = None
    positions: tuple[BrokerPosition, ...] = ()
    pending_orders: int = 0
    last_reconciled_at: datetime | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


_runtime = _Runtime()


async def shutdown_ig_runtime() -> None:
    """Stop order flow and close in-memory broker sessions during application shutdown."""

    if _runtime.broker is None:
        return
    _runtime.broker.safety.stop_new_trades("PROCESS_SHUTDOWN")
    await _runtime.broker.close()
    _runtime.broker = None
    _runtime.connected = False
    _runtime.account = None
    _runtime.positions = ()
    _runtime.pending_orders = 0


def _masked_account(value: str | None) -> str:
    if not value:
        return "Not connected"
    return f"••••{value[-4:]}"


def _managed_equity(session: Session, settings: Settings) -> Decimal:
    record = session.scalar(
        select(BacktestRecord)
        .where(BacktestRecord.status == "COMPLETED")
        .order_by(desc(BacktestRecord.completed_at))
        .limit(1)
    )
    return (
        record.final_equity
        if record is not None and record.final_equity is not None
        else settings.INITIAL_MANAGED_CAPITAL_GBP
    )


def _read_safety() -> DemoSafetyState | None:
    if _runtime.broker is not None:
        return _runtime.broker.safety.state()
    if not _STATE_PATH.exists():
        return None
    return PersistentDemoSafetyService(_STATE_PATH, resume_on_restart=True).state()


def _require_configured(settings: Settings) -> None:
    if not settings.ig_configured:
        raise HTTPException(
            status_code=409,
            detail="IG Demo credentials are not configured in the local backend environment",
        )


def _require_connected() -> IGDemoBroker:
    if not _runtime.connected or _runtime.broker is None:
        raise HTTPException(status_code=409, detail="connect to IG Demo first")
    return _runtime.broker


def _position_payload(position: BrokerPosition) -> dict[str, object]:
    return {
        "id": position.deal_id,
        "instrument": position.epic,
        "direction": "LONG" if position.direction.value == "BUY" else "SHORT",
        "strategy": "IG Demo managed position",
        "openedAt": (
            position.created_at.isoformat()
            if position.created_at
            else datetime.now(UTC).isoformat()
        ),
        "entryPrice": float(position.level),
        "currentPrice": float(position.level),
        "stopPrice": float(position.stop_level or 0),
        "targetPrice": float(position.limit_level or 0),
        "size": float(position.size),
        "currency": position.currency or "",
        "marginUsed": 0.0,
        "plannedRisk": 0.0,
        "unrealisedPnl": 0.0,
        "unrealisedPercent": 0.0,
        "regime": "UNKNOWN",
        "source": "IG_DEMO",
    }


def _confirmations(broker: IGDemoBroker | None) -> list[dict[str, object]]:
    if broker is None:
        return []
    status_map = {
        IntentStatus.ACCEPTED: "ACCEPTED",
        IntentStatus.REJECTED: "REJECTED",
    }
    return [
        {
            "id": item.intent_id,
            "timestamp": item.updated_at.isoformat(),
            "dealReference": item.deal_reference,
            "status": status_map.get(item.status, "PENDING"),
            "summary": f"{item.epic} {item.status.value}",
        }
        for item in broker.intent_store.list()[-50:]
    ]


@router.get("/status")
def status(
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, object]:
    safety = _read_safety()
    account = _runtime.account
    return {
        "configured": settings.ig_configured,
        "connected": _runtime.connected,
        "accountIdMasked": _masked_account(account.account_id if account else None),
        "brokerBalance": float(account.balance) if account else None,
        "managedEquity": float(_managed_equity(db, settings)),
        "availableFunds": float(account.available) if account else None,
        "streamStatus": (
            "CONNECTED"
            if _runtime.broker is not None
            and _runtime.broker.streaming is not None
            and _runtime.broker.streaming.state.value == "CONNECTED"
            else "DISCONNECTED"
            if settings.ig_configured
            else "NOT_CONFIGURED"
        ),
        "reconciliation": (
            "RECONCILED"
            if safety is not None and safety.reconciliation_complete
            else "RECONCILIATION_REQUIRED"
            if _runtime.connected
            else "NOT_CONNECTED"
        ),
        "autonomousMode": bool(safety and safety.automation_enabled),
        "newTradesAllowed": bool(
            safety
            and safety.automation_enabled
            and not safety.new_trades_blocked
            and safety.reconciliation_complete
            and not safety.critical_reasons
        ),
        "lastReconciledAt": (
            _runtime.last_reconciled_at.isoformat() if _runtime.last_reconciled_at else None
        ),
        "positions": [_position_payload(position) for position in _runtime.positions],
        "pendingOrders": _runtime.pending_orders,
        "confirmations": _confirmations(_runtime.broker),
        "markets": [],
        "blockReason": safety.block_reason if safety else "MANUAL_START_REQUIRED",
        "criticalReasons": list(safety.critical_reasons) if safety else [],
        "environment": "DEMO",
        "liveExecutionEnabled": False,
    }


@router.post("/connect")
async def connect(
    identity: Annotated[SessionIdentity, Depends(csrf_admin)],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, object]:
    _require_configured(settings)
    async with _runtime.lock:
        if _runtime.broker is None:
            _runtime.broker = IGDemoBroker(
                IGCredentials(
                    settings.IG_USERNAME,
                    settings.IG_PASSWORD,
                    settings.IG_API_KEY,
                    settings.IG_ACCOUNT_ID or None,
                ),
                persistence_database=_STATE_PATH,
            )
        try:
            await _runtime.broker.connect()
            accounts = tuple(await _runtime.broker.accounts())
        except IGError as exc:
            _runtime.connected = False
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        if not accounts:
            _runtime.connected = False
            raise HTTPException(status_code=502, detail="IG Demo returned no discoverable accounts")
        session = _runtime.broker.client.auth.session
        _runtime.account = next(
            (
                account
                for account in accounts
                if session and account.account_id == session.account_id
            ),
            accounts[0] if accounts else None,
        )
        _runtime.connected = True
        db.add(
            AuditEventRecord(
                timestamp=datetime.now(UTC),
                category="BROKER",
                severity="INFO",
                message="IG Demo connected",
                details={"actor": identity.username, "environment": "DEMO"},
            )
        )
        db.commit()
    return status(db, settings)


@router.post("/reconcile")
async def reconcile(
    identity: Annotated[SessionIdentity, Depends(csrf_admin)],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, object]:
    broker = _require_connected()
    async with _runtime.lock:
        try:
            report = await broker.reconcile()
            _runtime.positions = tuple(await broker.positions())
            _runtime.pending_orders = len(await broker.position_service.pending_orders())
        except IGError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        _runtime.last_reconciled_at = datetime.now(UTC)
        db.add(
            AuditEventRecord(
                timestamp=_runtime.last_reconciled_at,
                category="BROKER",
                severity="INFO" if report.complete else "WARNING",
                message="IG Demo reconciliation completed",
                details={
                    "actor": identity.username,
                    "complete": report.complete,
                    "broker_positions": report.broker_position_count,
                    "unknown_positions": len(report.unknown_broker_deal_ids),
                    "missing_positions": len(report.missing_broker_deal_ids),
                },
            )
        )
        db.commit()
    return status(db, settings)


@router.post("/autonomy/start")
def start_autonomy(
    identity: Annotated[SessionIdentity, Depends(csrf_admin)],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, object]:
    broker = _require_connected()
    try:
        broker.autonomy.start()
    except IGError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.add(
        AuditEventRecord(
            timestamp=datetime.now(UTC),
            category="CONTROL",
            severity="WARNING",
            message="autonomous IG Demo started",
            details={"actor": identity.username, "environment": "DEMO"},
        )
    )
    db.commit()
    return status(db, settings)


@router.post("/autonomy/stop")
def stop_autonomy(
    identity: Annotated[SessionIdentity, Depends(csrf_admin)],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, object]:
    safety = (
        _runtime.broker.safety
        if _runtime.broker is not None
        else PersistentDemoSafetyService(_STATE_PATH, resume_on_restart=True)
    )
    safety.stop_new_trades()
    db.add(
        AuditEventRecord(
            timestamp=datetime.now(UTC),
            category="CONTROL",
            severity="INFO",
            message="new IG Demo trades stopped",
            details={"actor": identity.username},
        )
    )
    db.commit()
    return status(db, settings)


@router.post("/positions/emergency-close")
async def emergency_close(
    identity: Annotated[SessionIdentity, Depends(csrf_admin)],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, object]:
    broker = _require_connected()
    async with _runtime.lock:
        try:
            report = await broker.autonomy.emergency_close_all()
            _runtime.positions = tuple(await broker.positions())
        except IGError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        db.add(
            AuditEventRecord(
                timestamp=datetime.now(UTC),
                category="CONTROL",
                severity="INFO" if report.complete else "CRITICAL",
                message="IG Demo emergency close completed",
                details={
                    "actor": identity.username,
                    "attempted": len(report.attempted_deal_ids),
                    "confirmed": len(report.confirmed_closed_deal_ids),
                    "unresolved": len(report.unresolved_deal_ids),
                },
            )
        )
        db.commit()
    return status(db, settings)
