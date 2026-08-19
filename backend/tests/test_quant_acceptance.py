from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from app.backtesting import Bar, FutureDataAccessError, GuardedBarSeries, MarketView
from app.backtesting.broker import HistoricalBroker
from app.backtesting.costs import CostModel, CostPreset
from app.backtesting.engine import BacktestConfig, HistoricalBacktestEngine
from app.core.clock import SimulationClock
from app.instruments.models import AssetClass, Instrument
from app.opportunities import Direction, OpportunityCandidate
from app.portfolio import ManagedCapitalLedger
from app.risk import PositionSizer, PositionSizingRequest, RiskEngine, RiskLimits
from app.strategies.base import Strategy

D = Decimal
UTC = UTC


def instrument() -> Instrument:
    return Instrument(
        id="TEST",
        name="Test Index",
        asset_class=AssetClass.INDEX,
        point_value=D("1"),
        min_deal_size=D("0.01"),
        size_step=D("0.01"),
        margin_factor=D("0.05"),
    )


def candidate(
    timestamp: datetime, *, requested_risk: Decimal | None = None
) -> OpportunityCandidate:
    return OpportunityCandidate(
        timestamp=timestamp,
        instrument_id="TEST",
        strategy_version_id="acceptance-v1",
        direction=Direction.LONG,
        signal_price=D("100"),
        expected_horizon=timedelta(hours=4),
        raw_signal_score=D("0.8"),
        calibrated_probability=D("0.60"),
        expected_upside=D("0.10"),
        expected_downside=D("0.05"),
        reward_risk_ratio=D("2"),
        historical_support=100,
        proposed_stop_distance=D("5"),
        proposed_target_distance=D("10"),
        requested_risk_fraction=requested_risk,
    )


class OneShotStrategy(Strategy):
    version_id = "acceptance-v1"

    def __init__(self, *, requested_risk: Decimal | None = None) -> None:
        self.requested_risk = requested_risk

    def evaluate(self, view: MarketView) -> OpportunityCandidate | None:
        return (
            candidate(view.latest.timestamp, requested_risk=self.requested_risk)
            if len(view.bars) == 1
            else None
        )


def sample_bars(*, ambiguous: bool = False) -> tuple[Bar, ...]:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    second_high = D("112")
    second_low = D("94") if ambiguous else D("99")
    return (
        Bar(start, D("100"), D("101"), D("99"), D("100"), instrument_id="TEST"),
        Bar(
            start + timedelta(hours=1),
            D("100"),
            second_high,
            second_low,
            D("101"),
            instrument_id="TEST",
        ),
        Bar(
            start + timedelta(hours=2),
            D("101"),
            D("102"),
            D("100"),
            D("101"),
            instrument_id="TEST",
        ),
    )


def relaxed_limits() -> RiskLimits:
    return RiskLimits(
        min_reward_risk=D("1"),
        max_market_exposure=D("5"),
        max_effective_leverage=D("5"),
        max_margin_usage=D("1"),
    )


def test_acceptance_compounding_uses_current_550_equity() -> None:
    ledger = ManagedCapitalLedger(D("500"))
    ledger.apply_return("winner", D("0.10"), timestamp=datetime(2024, 1, 1, tzinfo=UTC))
    assert ledger.equity == D("550.00")
    size = PositionSizer().calculate(
        PositionSizingRequest(
            equity=ledger.equity,
            risk_fraction=D("0.02"),
            entry_price=D("100"),
            stop_distance=D("1"),
            instrument=instrument(),
        )
    )
    assert size.accepted
    assert size.permitted_risk == D("11.00")
    assert size.size == D("11.00")


def test_acceptance_loss_compounding_uses_current_450_equity() -> None:
    ledger = ManagedCapitalLedger(D("500"))
    ledger.apply_return("loser", D("-0.10"), timestamp=datetime(2024, 1, 1, tzinfo=UTC))
    assert ledger.equity == D("450.00")
    size = PositionSizer().calculate(
        PositionSizingRequest(
            equity=ledger.equity,
            risk_fraction=D("0.02"),
            entry_price=D("100"),
            stop_distance=D("1"),
            instrument=instrument(),
        )
    )
    assert size.permitted_risk == D("9.00")
    assert size.size == D("9.00")


def test_acceptance_future_bar_access_is_blocked() -> None:
    bars = sample_bars()
    clock = SimulationClock(bars[0].timestamp)
    guarded = GuardedBarSeries(bars, clock)
    assert guarded.latest == bars[0]
    with pytest.raises(FutureDataAccessError):
        guarded.future()
    with pytest.raises(FutureDataAccessError):
        guarded.at(1)


def test_bounded_visible_tail_is_causal() -> None:
    bars = sample_bars()
    clock = SimulationClock(bars[1].timestamp)
    guarded = GuardedBarSeries(bars, clock)

    assert guarded.visible_tail(1) == (bars[1],)
    assert guarded.visible_tail(20) == bars[:2]
    assert guarded.visible_tail(0) == ()
    with pytest.raises(ValueError, match="cannot be negative"):
        guarded.visible_tail(-1)


def test_acceptance_realistic_costs_are_not_silently_zero() -> None:
    engine = HistoricalBacktestEngine(instrument(), OneShotStrategy(), risk_limits=relaxed_limits())
    zero = engine.run(sample_bars(), BacktestConfig(cost_preset=CostPreset.ZERO))
    realistic = engine.run(sample_bars(), BacktestConfig(cost_preset=CostPreset.REALISTIC))
    assert len(zero.trades) == len(realistic.trades) == 1
    assert zero.trades[0].total_cost == D("0.00")
    assert realistic.trades[0].total_cost > D("0")
    assert realistic.trades[0].net_pnl < realistic.trades[0].gross_pnl


def test_acceptance_risk_excess_never_reaches_broker() -> None:
    engine = HistoricalBacktestEngine(
        instrument(),
        OneShotStrategy(requested_risk=D("0.10")),
        risk_limits=relaxed_limits(),
    )
    result = engine.run(sample_bars())
    assert result.broker_orders_submitted == 0
    decisions = [event for event in result.audit_trail if event.event_type == "RISK_DECISION"]
    assert decisions and decisions[0].details["approved"] is False
    assert "requested trade risk exceeds profile limit" in decisions[0].details["reasons"]


def test_acceptance_stale_data_results_in_no_approved_order() -> None:
    timestamp = datetime(2024, 1, 1, tzinfo=UTC)
    ledger = ManagedCapitalLedger()
    risk = RiskEngine(relaxed_limits())
    decision = risk.evaluate(
        candidate(timestamp),
        instrument(),
        ledger,
        now=timestamp + timedelta(hours=3),
    )
    assert not decision.approved
    assert "stale data" in decision.reasons
    assert not risk.breakers.healthy


def test_acceptance_same_inputs_and_seed_are_reproducible() -> None:
    engine = HistoricalBacktestEngine(instrument(), OneShotStrategy(), risk_limits=relaxed_limits())
    config = BacktestConfig(seed=42)
    first = engine.run(sample_bars(), config)
    second = engine.run(sample_bars(), config)
    assert first.run_fingerprint == second.run_fingerprint
    assert first.trades == second.trades
    assert first.equity_curve == second.equity_curve
    assert first.audit_trail == second.audit_trail


def test_acceptance_large_demo_balance_never_changes_500_sizing_base() -> None:
    ledger = ManagedCapitalLedger(D("500"))
    ledger.record_broker_balance(D("1000000"))
    decision = RiskEngine(relaxed_limits()).evaluate(
        candidate(datetime(2024, 1, 1, tzinfo=UTC)),
        instrument(),
        ledger,
        now=datetime(2024, 1, 1, tzinfo=UTC),
    )
    assert decision.approved
    assert decision.equity_basis == D("500.00")
    assert decision.permitted_risk == D("10.00")
    assert ledger.broker_balance == D("1000000.00")


def test_broker_boundary_rejects_non_approved_objects() -> None:
    broker = HistoricalBroker(instrument())
    with pytest.raises(Exception, match="approved RiskEngine"):
        broker.execute_order(object(), sample_bars()[1])  # type: ignore[arg-type]
    assert broker.submitted_order_count == 0


def test_single_market_constructor_passes_default_taper_to_risk_gate() -> None:
    limits = RiskLimits(
        risk_per_trade=D("0.06"),
        max_open_risk=D("0.18"),
        max_market_exposure=D("5"),
        max_effective_leverage=D("5"),
        max_margin_usage=D("1"),
        max_correlated_risk=D("0.12"),
        min_reward_risk=D("1"),
    )
    result = HistoricalBacktestEngine(
        instrument(),
        OneShotStrategy(),
        risk_limits=limits,
        risk_taper=True,
    ).run(sample_bars(), BacktestConfig(cost_preset=CostPreset.ZERO))
    decision = next(event for event in result.audit_trail if event.event_type == "RISK_DECISION")
    assert decision.details["approved"] is True
    assert decision.details["risk_fraction"] == "0.04"
    assert decision.details["risk_taper_cap"] == "0.04"

    untapered = HistoricalBacktestEngine(
        instrument(),
        OneShotStrategy(),
        risk_limits=limits,
    ).run(sample_bars(), BacktestConfig(cost_preset=CostPreset.ZERO))
    untapered_decision = next(
        event for event in untapered.audit_trail if event.event_type == "RISK_DECISION"
    )
    assert untapered_decision.details["risk_fraction"] == "0.06"
    assert untapered_decision.details["risk_taper_cap"] is None
    assert result.run_fingerprint != untapered.run_fingerprint


def test_single_market_fingerprint_covers_all_outcome_inputs() -> None:
    source = sample_bars()
    base_limits = relaxed_limits()

    def run_fingerprint(
        *,
        selected_instrument: Instrument | None = None,
        selected_strategy: Strategy | None = None,
        selected_limits: RiskLimits | None = None,
        selected_bars: tuple[Bar, ...] | None = None,
        config: BacktestConfig | None = None,
        cost_model: CostModel | None = None,
    ) -> str:
        return (
            HistoricalBacktestEngine(
                selected_instrument or instrument(),
                selected_strategy or OneShotStrategy(),
                risk_limits=selected_limits or base_limits,
                cost_model=cost_model,
            )
            .run(selected_bars or source, config or BacktestConfig())
            .run_fingerprint
        )

    baseline = run_fingerprint()
    config_variants = (
        BacktestConfig(starting_equity=D("600")),
        BacktestConfig(execution_delay_bars=2),
        BacktestConfig(maximum_holding_bars=1),
        BacktestConfig(operational_costs=D("1")),
        BacktestConfig(seed=99),
        BacktestConfig(close_positions_at_end=False),
        BacktestConfig(cost_preset=CostPreset.STRESSED),
    )
    for config in config_variants:
        assert run_fingerprint(config=config) != baseline

    changed_volume = (replace(source[0], volume=D("123")), *source[1:])
    changed_quality = (replace(source[0], data_quality=D("0.99")), *source[1:])
    assert run_fingerprint(selected_bars=changed_volume) != baseline
    assert run_fingerprint(selected_bars=changed_quality) != baseline
    assert (
        run_fingerprint(selected_instrument=replace(instrument(), point_value=D("2"))) != baseline
    )
    assert (
        run_fingerprint(selected_limits=replace(base_limits, max_daily_loss=D("0.04"))) != baseline
    )
    assert run_fingerprint(selected_strategy=OneShotStrategy(requested_risk=D("0.01"))) != baseline
    assert run_fingerprint(cost_model=CostModel.from_preset(CostPreset.OPTIMISTIC)) != baseline
