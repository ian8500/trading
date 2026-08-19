from __future__ import annotations

import stat
from decimal import Decimal
from pathlib import Path

import pytest
from app.brokers.base import BrokerPosition, Direction
from app.brokers.ig.orders import IGOrderIntent, IntentStatus, SQLiteOrderIntentStore
from app.brokers.ig.positions import IGWorkingOrder
from app.brokers.ig.reconciliation import IGReconciliationService
from app.brokers.ig.safety import PersistentDemoSafetyService

EPIC = "CS.D.GBPUSD.CFD.IP"


def position(
    deal_id: str = "DEAL-1", deal_reference: str | None = "intent-reference"
) -> BrokerPosition:
    return BrokerPosition(
        deal_id=deal_id,
        deal_reference=deal_reference,
        epic=EPIC,
        direction=Direction.BUY,
        size=Decimal("1"),
        level=Decimal("1.2722"),
        currency="GBP",
        stop_level=Decimal("1.2672"),
        limit_level=None,
        controlled_risk=False,
    )


class FakePositions:
    def __init__(
        self,
        positions: tuple[BrokerPosition, ...] = (),
        working_orders: tuple[IGWorkingOrder, ...] = (),
    ) -> None:
        self._positions = positions
        self._working_orders = working_orders

    async def list(self) -> tuple[BrokerPosition, ...]:
        return self._positions

    async def pending_orders(self) -> tuple[IGWorkingOrder, ...]:
        return self._working_orders


def intent(intent_id: str = "intent-reference") -> IGOrderIntent:
    return IGOrderIntent(
        epic=EPIC,
        direction=Direction.BUY,
        size=Decimal("1"),
        currency_code="GBP",
        risk_approval_id="risk-approval",
        risk_approved=True,
        stop_distance=Decimal("5"),
        intent_id=intent_id,
    )


def test_kill_switch_and_manual_restart_requirement_persist(tmp_path: Path) -> None:
    database = tmp_path / "ig.sqlite3"
    first = PersistentDemoSafetyService(database)
    first.record_reconciliation(True)
    started = first.start_autonomous_demo()
    assert started.automation_enabled
    tripped = first.trip("AMBIGUOUS_ORDER_STATUS")
    assert tripped.new_trades_blocked

    restarted = PersistentDemoSafetyService(database)
    state = restarted.state()
    assert not state.automation_enabled
    assert state.new_trades_blocked
    assert not state.reconciliation_complete
    assert "AMBIGUOUS_ORDER_STATUS" in state.critical_reasons
    assert stat.S_IMODE(database.stat().st_mode) == 0o600


@pytest.mark.asyncio
async def test_empty_matching_broker_state_reconciles_but_does_not_auto_start(
    tmp_path: Path,
) -> None:
    database = tmp_path / "ig.sqlite3"
    safety = PersistentDemoSafetyService(database)
    store = SQLiteOrderIntentStore(database)
    service = IGReconciliationService(FakePositions(), store, safety)  # type: ignore[arg-type]
    report = await service.reconcile()
    assert report.complete
    assert safety.state().reconciliation_complete
    assert safety.state().new_trades_blocked
    assert not safety.state().automation_enabled
    assert safety.start_autonomous_demo().automation_enabled


@pytest.mark.asyncio
async def test_unknown_broker_position_triggers_persistent_reconciliation_breaker(
    tmp_path: Path,
) -> None:
    database = tmp_path / "ig.sqlite3"
    safety = PersistentDemoSafetyService(database)
    store = SQLiteOrderIntentStore(database)
    service = IGReconciliationService(
        FakePositions((position("EXTERNAL", None),)),  # type: ignore[arg-type]
        store,
        safety,
    )
    report = await service.reconcile()
    assert not report.complete
    assert report.unknown_broker_deal_ids == ("EXTERNAL",)
    assert "RECONCILIATION_REQUIRED" in safety.state().critical_reasons


@pytest.mark.asyncio
async def test_matching_internal_position_reconciles_and_missing_position_does_not(
    tmp_path: Path,
) -> None:
    database = tmp_path / "ig.sqlite3"
    safety = PersistentDemoSafetyService(database)
    store = SQLiteOrderIntentStore(database)
    order = intent()
    store.create_pending(order)
    store.transition(order.intent_id, IntentStatus.ACCEPTED, deal_id="DEAL-1")

    matching = IGReconciliationService(
        FakePositions((position(),)),  # type: ignore[arg-type]
        store,
        safety,
    )
    report = await matching.reconcile()
    assert report.complete
    assert report.matched_deal_ids == ("DEAL-1",)

    missing = IGReconciliationService(FakePositions(), store, safety)  # type: ignore[arg-type]
    report = await missing.reconcile()
    assert not report.complete
    assert report.missing_broker_deal_ids == ("DEAL-1",)


@pytest.mark.asyncio
async def test_any_working_order_is_unknown_in_immediate_order_v1(tmp_path: Path) -> None:
    database = tmp_path / "ig.sqlite3"
    safety = PersistentDemoSafetyService(database)
    store = SQLiteOrderIntentStore(database)
    working = IGWorkingOrder(
        deal_id="WORKING-1",
        epic=EPIC,
        direction=Direction.BUY,
        size=Decimal("1"),
        order_type="LIMIT",
        order_level=Decimal("1.25"),
        stop_distance=Decimal("5"),
        guaranteed_stop=False,
        raw={},
    )
    service = IGReconciliationService(
        FakePositions(working_orders=(working,)),  # type: ignore[arg-type]
        store,
        safety,
    )
    report = await service.reconcile()
    assert not report.complete
    assert report.unknown_working_order_ids == ("WORKING-1",)


@pytest.mark.asyncio
async def test_position_matching_a_rejected_intent_is_still_unknown(tmp_path: Path) -> None:
    database = tmp_path / "ig.sqlite3"
    safety = PersistentDemoSafetyService(database)
    store = SQLiteOrderIntentStore(database)
    order = intent()
    store.create_pending(order)
    store.transition(order.intent_id, IntentStatus.REJECTED, reason="KNOWN_REJECTION")
    service = IGReconciliationService(
        FakePositions((position(),)),  # type: ignore[arg-type]
        store,
        safety,
    )
    report = await service.reconcile()
    assert report.unknown_broker_deal_ids == ("DEAL-1",)
    assert not report.complete
