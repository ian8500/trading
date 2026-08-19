from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from app.brokers.base import (
    BrokerOrderStatus,
    BrokerPosition,
    Direction,
    MarketCapability,
    PriceQuote,
)
from app.brokers.ig.client import IGClient
from app.brokers.ig.confirmations import IGConfirmation
from app.brokers.ig.errors import IGOrderSafetyError, IGTransportError
from app.brokers.ig.orders import (
    IGOrderIntent,
    IGOrdersService,
    IntentStatus,
    SQLiteOrderIntentStore,
)
from app.brokers.ig.safety import PersistentDemoSafetyService
from app.brokers.ig.transport import IGResponse
from ig_fakes import ScriptedTransport, TransportStep, demo_credentials, login_response

NOW = datetime(2026, 8, 19, 10, 0, 2, tzinfo=UTC)
EPIC = "CS.D.GBPUSD.CFD.IP"


def capability(*, minimum_size: Decimal = Decimal("0.5")) -> MarketCapability:
    return MarketCapability(
        epic=EPIC,
        instrument_name="GBP/USD",
        instrument_type="CURRENCIES",
        currency="GBP",
        market_status="TRADEABLE",
        opening_hours=(),
        tradeable=True,
        market_order_supported=True,
        force_open_supported=True,
        stops_limits_supported=True,
        snapshot_pricing_supported=True,
        streaming_pricing_supported=True,
        historical_pricing_supported=True,
        minimum_deal_size=minimum_size,
        maximum_deal_size=None,
        contract_size=Decimal("1"),
        value_of_one_pip=Decimal("1"),
        margin_factor=Decimal("3.33"),
        controlled_risk_supported=True,
        guaranteed_stop_supported=True,
        minimum_stop_distance=Decimal("1"),
        minimum_guaranteed_stop_distance=Decimal("2"),
        minimum_limit_distance=Decimal("1"),
        expiry="-",
        rolling=True,
        overnight_funding_applicable=True,
        raw_rule_units={
            "minDealSize": "POINTS",
            "minNormalStopOrLimitDistance": "POINTS",
            "minControlledRiskStopDistance": "POINTS",
        },
    )


class FakeCapabilities:
    def __init__(self, value: MarketCapability | None = None) -> None:
        self.value = value or capability()

    async def discover(self, epic: str) -> MarketCapability:
        assert epic == EPIC
        return self.value


class FakePrices:
    async def snapshot(self, epic: str) -> PriceQuote:
        assert epic == EPIC
        return PriceQuote(
            epic=epic,
            bid=Decimal("1.2720"),
            ask=Decimal("1.2722"),
            timestamp=datetime(2026, 8, 19, 10, 0, 0, tzinfo=UTC),
            market_status="TRADEABLE",
        )


class FakeConfirmations:
    def __init__(
        self,
        *,
        waits: list[IGConfirmation | None] | None = None,
        gets: list[IGConfirmation | None] | None = None,
    ) -> None:
        self.waits = list(waits or [])
        self.gets = list(gets or [])

    async def wait_for(self, deal_reference: str) -> IGConfirmation | None:
        del deal_reference
        return self.waits.pop(0) if self.waits else None

    async def get(self, deal_reference: str) -> IGConfirmation | None:
        del deal_reference
        return self.gets.pop(0) if self.gets else None


class FakePositions:
    def __init__(
        self, position: BrokerPosition | None = None, *, protection_fails: bool = False
    ) -> None:
        self.position = position
        self.protection_fails = protection_fails
        self.close_count = 0
        self.update_count = 0

    async def list(self) -> tuple[BrokerPosition, ...]:
        return (self.position,) if self.position else ()

    async def get(self, deal_id: str) -> BrokerPosition | None:
        if self.position is not None:
            assert deal_id == self.position.deal_id
        return self.position

    async def update_protection(
        self,
        deal_id: str,
        *,
        stop_level: Decimal,
        guaranteed_stop: bool,
    ) -> str:
        del deal_id, stop_level, guaranteed_stop
        self.update_count += 1
        if self.protection_fails:
            raise IGTransportError(request_may_have_been_sent=None)
        return "protection-reference"

    async def close_position(self, position: BrokerPosition) -> str:
        assert position is self.position
        self.close_count += 1
        return "close-reference"


def confirmation(
    intent_id: str,
    *,
    accepted: bool = True,
    stop_distance: Decimal | None = Decimal("5"),
    reason: str | None = None,
) -> IGConfirmation:
    return IGConfirmation(
        deal_reference=intent_id,
        deal_status="ACCEPTED" if accepted else "REJECTED",
        deal_id="DEAL-1",
        status="OPEN" if accepted else None,
        reason=reason,
        epic=EPIC,
        stop_level=None,
        stop_distance=stop_distance,
        limit_level=None,
        raw={"dealReference": intent_id},
    )


def make_intent(**overrides) -> IGOrderIntent:
    values = {
        "epic": EPIC,
        "direction": Direction.BUY,
        "size": Decimal("1"),
        "currency_code": "GBP",
        "risk_approval_id": "risk-approval-1",
        "risk_approved": True,
        "stop_distance": Decimal("5"),
    }
    values.update(overrides)
    return IGOrderIntent(**values)


def make_service(
    database: Path,
    transport: ScriptedTransport,
    confirmations: FakeConfirmations,
    positions: FakePositions | None = None,
    capabilities: FakeCapabilities | None = None,
) -> tuple[IGOrdersService, PersistentDemoSafetyService, SQLiteOrderIntentStore]:
    client = IGClient(demo_credentials(), transport=transport)
    safety = PersistentDemoSafetyService(database)
    safety.record_reconciliation(True)
    safety.start_autonomous_demo()
    store = SQLiteOrderIntentStore(database)
    service = IGOrdersService(
        client,
        confirmations,  # type: ignore[arg-type]
        positions or FakePositions(),  # type: ignore[arg-type]
        FakePrices(),  # type: ignore[arg-type]
        capabilities or FakeCapabilities(),  # type: ignore[arg-type]
        store,
        safety,
        clock=lambda: NOW,
    )
    return service, safety, store


@pytest.mark.asyncio
async def test_order_is_persisted_acknowledged_confirmed_and_protected(tmp_path: Path) -> None:
    intent = make_intent()
    accepted = confirmation(intent.intent_id)
    transport = ScriptedTransport(
        TransportStep("POST", "/gateway/deal/session", login_response()),
        TransportStep(
            "POST",
            "/gateway/deal/positions/otc",
            IGResponse(200, {}, {"dealReference": intent.intent_id}),
        ),
    )
    service, _, store = make_service(
        tmp_path / "ig.sqlite3", transport, FakeConfirmations(waits=[accepted])
    )
    result = await service.submit(intent)
    assert result.status == BrokerOrderStatus.ACCEPTED
    assert result.deal_id == "DEAL-1"
    assert store.get(intent.intent_id).status == IntentStatus.ACCEPTED  # type: ignore[union-attr]
    order_call = next(call for call in transport.calls if call["path"].endswith("positions/otc"))
    assert order_call["json_body"]["dealReference"] == intent.intent_id
    assert order_call["json_body"]["stopDistance"] == 5.0
    assert order_call["json_body"]["timeInForce"] == "FILL_OR_KILL"


@pytest.mark.asyncio
async def test_known_order_rejection_is_terminal_and_not_retried(tmp_path: Path) -> None:
    intent = make_intent()
    transport = ScriptedTransport(
        TransportStep("POST", "/gateway/deal/session", login_response()),
        TransportStep(
            "POST",
            "/gateway/deal/positions/otc",
            IGResponse(400, {}, {"errorCode": "error.trading.otc.market-orders.not-supported"}),
        ),
    )
    service, _, _ = make_service(tmp_path / "ig.sqlite3", transport, FakeConfirmations())
    result = await service.submit(intent)
    assert result.status == BrokerOrderStatus.REJECTED
    assert len([call for call in transport.calls if call["path"].endswith("positions/otc")]) == 1


@pytest.mark.asyncio
async def test_ambiguous_response_is_reconciled_but_never_resubmitted(tmp_path: Path) -> None:
    intent = make_intent()
    transport = ScriptedTransport(
        TransportStep("POST", "/gateway/deal/session", login_response()),
        TransportStep(
            "POST",
            "/gateway/deal/positions/otc",
            IGTransportError(request_may_have_been_sent=None),
        ),
    )
    confirmations = FakeConfirmations()
    service, safety, store = make_service(tmp_path / "ig.sqlite3", transport, confirmations)
    first = await service.submit(intent)
    second = await service.submit(intent)
    assert first.status == second.status == BrokerOrderStatus.AMBIGUOUS
    assert store.get(intent.intent_id).status == IntentStatus.AMBIGUOUS  # type: ignore[union-attr]
    assert "AMBIGUOUS_ORDER_STATUS" in safety.state().critical_reasons
    assert len([call for call in transport.calls if call["path"].endswith("positions/otc")]) == 1


@pytest.mark.asyncio
async def test_reusing_intent_id_with_different_parameters_trips_breaker(tmp_path: Path) -> None:
    intent = make_intent()
    accepted = confirmation(intent.intent_id)
    transport = ScriptedTransport(
        TransportStep("POST", "/gateway/deal/session", login_response()),
        TransportStep(
            "POST",
            "/gateway/deal/positions/otc",
            IGResponse(200, {}, {"dealReference": intent.intent_id}),
        ),
    )
    service, safety, _ = make_service(
        tmp_path / "ig.sqlite3", transport, FakeConfirmations(waits=[accepted])
    )
    assert (await service.submit(intent)).status == BrokerOrderStatus.ACCEPTED

    conflicting = make_intent(intent_id=intent.intent_id, size=Decimal("2"))
    with pytest.raises(IGOrderSafetyError):
        await service.submit(conflicting)
    assert "INTENT_ID_CONFLICT" in safety.state().critical_reasons
    assert len([call for call in transport.calls if call["path"].endswith("positions/otc")]) == 1


@pytest.mark.asyncio
async def test_delayed_confirmation_can_resolve_without_resubmission(tmp_path: Path) -> None:
    intent = make_intent()
    accepted = confirmation(intent.intent_id)
    transport = ScriptedTransport(
        TransportStep("POST", "/gateway/deal/session", login_response()),
        TransportStep(
            "POST",
            "/gateway/deal/positions/otc",
            IGResponse(200, {}, {"dealReference": intent.intent_id}),
        ),
    )
    confirmations = FakeConfirmations(waits=[None], gets=[accepted])
    service, _, _ = make_service(tmp_path / "ig.sqlite3", transport, confirmations)
    result = await service.submit(intent)
    assert result.status == BrokerOrderStatus.ACCEPTED
    assert len([call for call in transport.calls if call["path"].endswith("positions/otc")]) == 1


@pytest.mark.asyncio
async def test_unknown_confirmation_status_is_ambiguous_not_rejected(tmp_path: Path) -> None:
    intent = make_intent()
    malformed = IGConfirmation(
        deal_reference=intent.intent_id,
        deal_status="UNKNOWN",
        deal_id="DEAL-1",
        status=None,
        reason=None,
        epic=EPIC,
        stop_level=None,
        stop_distance=None,
        limit_level=None,
        raw={"dealReference": intent.intent_id},
    )
    transport = ScriptedTransport(
        TransportStep("POST", "/gateway/deal/session", login_response()),
        TransportStep(
            "POST",
            "/gateway/deal/positions/otc",
            IGResponse(200, {}, {"dealReference": intent.intent_id}),
        ),
    )
    service, safety, store = make_service(
        tmp_path / "ig.sqlite3", transport, FakeConfirmations(waits=[malformed])
    )
    result = await service.submit(intent)
    assert result.status == BrokerOrderStatus.AMBIGUOUS
    assert store.get(intent.intent_id).status == IntentStatus.AMBIGUOUS  # type: ignore[union-attr]
    assert "AMBIGUOUS_ORDER_STATUS" in safety.state().critical_reasons


@pytest.mark.asyncio
async def test_mismatched_confirmation_identity_is_ambiguous(tmp_path: Path) -> None:
    intent = make_intent()
    mismatched = IGConfirmation(
        deal_reference=intent.intent_id,
        deal_status="ACCEPTED",
        deal_id="DEAL-1",
        status="OPEN",
        reason="SUCCESS",
        epic="CS.D.EURUSD.CFD.IP",
        stop_level=None,
        stop_distance=Decimal("5"),
        limit_level=None,
        raw={"dealReference": intent.intent_id},
    )
    transport = ScriptedTransport(
        TransportStep("POST", "/gateway/deal/session", login_response()),
        TransportStep(
            "POST",
            "/gateway/deal/positions/otc",
            IGResponse(200, {}, {"dealReference": intent.intent_id}),
        ),
    )
    service, safety, _ = make_service(
        tmp_path / "ig.sqlite3", transport, FakeConfirmations(waits=[mismatched])
    )
    result = await service.submit(intent)
    assert result.status == BrokerOrderStatus.AMBIGUOUS
    assert "AMBIGUOUS_ORDER_STATUS" in safety.state().critical_reasons


@pytest.mark.asyncio
async def test_unconfirmed_protective_stop_closes_and_suspends(tmp_path: Path) -> None:
    intent = make_intent()
    open_confirmation = confirmation(intent.intent_id, stop_distance=None)
    close_confirmation = confirmation("close-reference", stop_distance=None)
    position = BrokerPosition(
        deal_id="DEAL-1",
        deal_reference=intent.intent_id,
        epic=EPIC,
        direction=Direction.BUY,
        size=Decimal("1"),
        level=Decimal("1.2722"),
        currency="GBP",
        stop_level=None,
        limit_level=None,
        controlled_risk=False,
    )
    positions = FakePositions(position, protection_fails=True)
    confirmations = FakeConfirmations(waits=[open_confirmation, close_confirmation])
    transport = ScriptedTransport(
        TransportStep("POST", "/gateway/deal/session", login_response()),
        TransportStep(
            "POST",
            "/gateway/deal/positions/otc",
            IGResponse(200, {}, {"dealReference": intent.intent_id}),
        ),
    )
    service, safety, store = make_service(
        tmp_path / "ig.sqlite3", transport, confirmations, positions
    )
    result = await service.submit(intent)
    assert result.status == BrokerOrderStatus.AMBIGUOUS
    assert positions.update_count == 1
    assert positions.close_count == 1
    assert store.get(intent.intent_id).status == IntentStatus.CLOSED_FOR_SAFETY  # type: ignore[union-attr]
    assert "PROTECTIVE_STOP_FAILURE" in safety.state().critical_reasons


@pytest.mark.asyncio
async def test_risk_rejection_cannot_reach_authentication_or_order_transport(
    tmp_path: Path,
) -> None:
    intent = make_intent(risk_approved=False)
    transport = ScriptedTransport()
    service, _, _ = make_service(tmp_path / "ig.sqlite3", transport, FakeConfirmations())
    with pytest.raises(IGOrderSafetyError):
        await service.submit(intent)
    assert transport.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "intent",
    [
        make_intent(stop_distance=None, stop_level=Decimal("1.2715")),
        make_intent(
            direction=Direction.SELL,
            stop_distance=None,
            stop_level=Decimal("1.2725"),
        ),
        make_intent(limit_distance=Decimal("0.5")),
    ],
)
async def test_stop_and_limit_levels_must_obey_discovered_minimums(
    tmp_path: Path,
    intent: IGOrderIntent,
) -> None:
    transport = ScriptedTransport()
    service, _, _ = make_service(
        tmp_path / f"{intent.intent_id}.sqlite3", transport, FakeConfirmations()
    )
    with pytest.raises(IGOrderSafetyError, match="minimum distance"):
        await service.submit(intent)
    assert transport.calls == []


@pytest.mark.asyncio
async def test_protective_stop_level_must_be_on_loss_side(tmp_path: Path) -> None:
    intent = make_intent(stop_distance=None, stop_level=Decimal("1.2730"))
    transport = ScriptedTransport()
    service, _, _ = make_service(tmp_path / "ig.sqlite3", transport, FakeConfirmations())
    with pytest.raises(IGOrderSafetyError, match="below the entry"):
        await service.submit(intent)
    assert transport.calls == []
