from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import app.backtesting.portfolio_engine as portfolio_engine_module
import pytest
from app.backtesting import Bar, MarketView
from app.backtesting.costs import CostModel, CostPreset
from app.backtesting.engine import BacktestConfig
from app.backtesting.portfolio_engine import PortfolioBacktestEngine
from app.instruments.models import AssetClass, Instrument
from app.opportunities import Direction, OpportunityCandidate
from app.risk import RiskLimits
from app.strategies.base import Strategy

D = Decimal


def market(identifier: str, cluster: str = "RISK") -> Instrument:
    return Instrument(
        identifier,
        identifier,
        AssetClass.INDEX,
        point_value=D("1"),
        min_deal_size=D("0.01"),
        size_step=D("0.01"),
        margin_factor=D("0.01"),
        correlation_cluster=cluster,
    )


class ScheduledSignal(Strategy):
    def __init__(
        self,
        instrument_id: str,
        at_visible_count: int,
        *,
        probability: str = "0.60",
    ) -> None:
        self.instrument_id = instrument_id
        self.at_visible_count = at_visible_count
        self.probability = D(probability)
        self.version_id = f"{instrument_id}-v1"

    def evaluate(self, view: MarketView) -> OpportunityCandidate | None:
        if len(view.bars) != self.at_visible_count:
            return None
        bar = view.latest
        return OpportunityCandidate(
            timestamp=bar.timestamp,
            instrument_id=self.instrument_id,
            strategy_version_id=self.version_id,
            direction=Direction.LONG,
            signal_price=bar.close,
            expected_horizon=timedelta(hours=2),
            raw_signal_score=self.probability,
            calibrated_probability=self.probability,
            expected_upside=D("0.05"),
            expected_downside=D("0.05"),
            reward_risk_ratio=D("1.5"),
            historical_support=100,
            proposed_stop_distance=D("5"),
            proposed_target_distance=D("5"),
            correlation_cluster=view.instrument.correlation_cluster,
        )


class RepeatedSignal(Strategy):
    version_id = "repeated-v1"

    def __init__(self, instrument_id: str, visible_counts: frozenset[int]) -> None:
        self.instrument_id = instrument_id
        self.visible_counts = visible_counts

    def evaluate(self, view: MarketView) -> OpportunityCandidate | None:
        if len(view.bars) not in self.visible_counts:
            return None
        bar = view.latest
        return OpportunityCandidate(
            timestamp=bar.timestamp,
            instrument_id=self.instrument_id,
            strategy_version_id=self.version_id,
            direction=Direction.LONG,
            signal_price=bar.close,
            expected_horizon=timedelta(days=1),
            raw_signal_score=D("0.8"),
            calibrated_probability=D("0.6"),
            expected_upside=D("0.10"),
            expected_downside=D("0.05"),
            reward_risk_ratio=D("2"),
            historical_support=100,
            proposed_stop_distance=D("5"),
            proposed_target_distance=D("10"),
            correlation_cluster=view.instrument.correlation_cluster,
        )


def data(identifier: str) -> tuple[Bar, ...]:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    return (
        Bar(start, D("100"), D("101"), D("99"), D("100"), instrument_id=identifier),
        Bar(
            start + timedelta(hours=1),
            D("100"),
            D("106"),
            D("99"),
            D("100"),
            instrument_id=identifier,
        ),
        Bar(
            start + timedelta(hours=2),
            D("100"),
            D("106"),
            D("99"),
            D("100"),
            instrument_id=identifier,
        ),
        Bar(
            start + timedelta(hours=3),
            D("100"),
            D("101"),
            D("99"),
            D("100"),
            instrument_id=identifier,
        ),
    )


def portfolio_limits(
    *,
    risk_per_trade: Decimal | None = None,
    max_open_risk: Decimal | None = None,
    max_correlated_risk: Decimal | None = None,
) -> RiskLimits:
    return RiskLimits(
        risk_per_trade=D("0.02") if risk_per_trade is None else risk_per_trade,
        max_open_risk=D("0.06") if max_open_risk is None else max_open_risk,
        max_correlated_risk=(D("0.04") if max_correlated_risk is None else max_correlated_risk),
        min_reward_risk=D("1"),
        max_market_exposure=D("10"),
        max_effective_leverage=D("10"),
        max_margin_usage=D("1"),
    )


def test_candidates_are_ranked_cross_market_and_pending_risk_is_reserved() -> None:
    instruments = {"A": market("A"), "B": market("B")}
    strategies = {
        "A": ScheduledSignal("A", 1, probability="0.70"),
        "B": ScheduledSignal("B", 1, probability="0.55"),
    }
    engine = PortfolioBacktestEngine(
        instruments,
        strategies,
        risk_limits=portfolio_limits(max_correlated_risk=D("0.025")),
    )
    result = engine.run(
        {"A": data("A"), "B": data("B")},
        BacktestConfig(cost_preset=CostPreset.ZERO, bar_interval="1h"),
    )
    rankings = [event for event in result.audit_trail if event.event_type == "CANDIDATES_RANKED"]
    assert rankings[0].details["ranking"][0]["instrument_id"] == "A"
    created = next(event for event in result.audit_trail if event.event_type == "CANDIDATE_CREATED")
    assert created.details["signal_price"] == "100"
    assert created.details["expected_growth_score"]
    assert created.details["score_components"]["expected_log_growth"]
    assert created.details["historical_support"] == 100
    assert "explanation" in created.details
    challenged = next(
        event for event in result.audit_trail if event.event_type == "CANDIDATE_CHALLENGED"
    )
    assert "original_score" in challenged.details
    assert "supporting_factors" in challenged.details
    assert "penalties" in challenged.details
    decisions = [event for event in result.audit_trail if event.event_type == "RISK_DECISION"]
    assert decisions[0].details["instrument_id"] == "A"
    assert decisions[0].details["approved"] is True
    assert decisions[1].details["instrument_id"] == "B"
    assert decisions[1].details["approved"] is False
    assert "maximum correlated exposure exceeded" in decisions[1].details["reasons"]
    assert result.orders_by_instrument == {"A": 1, "B": 0}


def test_shared_ledger_compounds_before_later_market_is_sized() -> None:
    instruments = {"A": market("A", "A"), "B": market("B", "B")}
    strategies = {
        "A": ScheduledSignal("A", 1),
        "B": ScheduledSignal("B", 2),
    }
    result = PortfolioBacktestEngine(
        instruments,
        strategies,
        risk_limits=portfolio_limits(),
    ).run(
        {"A": data("A"), "B": data("B")},
        BacktestConfig(cost_preset=CostPreset.ZERO, bar_interval="1h"),
    )
    assert len(result.trades) == 2
    assert result.trades[0].instrument_id == "A"
    assert result.trades[0].managed_equity_after == D("510.00")
    b_decision = next(
        event
        for event in result.audit_trail
        if event.event_type == "RISK_DECISION" and event.details["instrument_id"] == "B"
    )
    assert b_decision.details["equity_basis"] == "510.00"
    assert b_decision.details["planned_monetary_risk"] == "10.20"
    assert result.trades[1].managed_equity_before == D("510.00")


def test_multi_year_portfolio_resumes_after_daily_loss_period_ends() -> None:
    identifier = "A"
    start = datetime(2023, 12, 30, tzinfo=UTC)
    bars = (
        Bar(start, D("100"), D("101"), D("99"), D("100"), instrument_id=identifier),
        Bar(
            start + timedelta(days=1),
            D("100"),
            D("101"),
            D("94"),
            D("100"),
            instrument_id=identifier,
        ),
        Bar(
            datetime(2025, 1, 2, tzinfo=UTC),
            D("100"),
            D("101"),
            D("99"),
            D("100"),
            instrument_id=identifier,
        ),
        Bar(
            datetime(2025, 1, 3, tzinfo=UTC),
            D("100"),
            D("101"),
            D("99"),
            D("100"),
            instrument_id=identifier,
        ),
    )
    limits = replace(portfolio_limits(), max_daily_loss=D("0.01"))
    result = PortfolioBacktestEngine(
        {identifier: market(identifier, identifier)},
        {identifier: RepeatedSignal(identifier, frozenset((1, 2, 3)))},
        risk_limits=limits,
    ).run({identifier: bars}, BacktestConfig(cost_preset=CostPreset.ZERO))

    decisions = [event for event in result.audit_trail if event.event_type == "RISK_DECISION"]
    assert [decision.details["approved"] for decision in decisions] == [True, False, True]
    assert "daily loss circuit breaker" in decisions[1].details["reasons"]
    assert decisions[2].timestamp.year == 2025
    reset = next(
        event for event in result.audit_trail if event.event_type == "CIRCUIT_BREAKER_RESET"
    )
    assert reset.details["kind"] == "DAILY_LOSS"
    assert reset.timestamp == datetime(2025, 1, 2, tzinfo=UTC)
    assert result.broker_orders_submitted == 2
    assert len(result.trades) == 2


def test_multi_market_event_stream_and_result_are_reproducible() -> None:
    instruments = {"A": market("A", "A"), "B": market("B", "B")}
    strategies = {"A": ScheduledSignal("A", 1), "B": ScheduledSignal("B", 2)}
    engine = PortfolioBacktestEngine(instruments, strategies, risk_limits=portfolio_limits())
    source = {"A": data("A"), "B": data("B")}
    first = engine.run(
        source,
        BacktestConfig(cost_preset=CostPreset.ZERO, seed=99, bar_interval="1h"),
    )
    second = engine.run(
        source,
        BacktestConfig(cost_preset=CostPreset.ZERO, seed=99, bar_interval="1h"),
    )
    assert first.run_fingerprint == second.run_fingerprint
    assert first.trades == second.trades
    assert first.audit_trail == second.audit_trail
    timestamps = [event.timestamp for event in first.audit_trail]
    assert timestamps == sorted(timestamps)


def test_portfolio_constructor_passes_default_taper_to_risk_gate() -> None:
    engine = PortfolioBacktestEngine(
        {"A": market("A", "A")},
        {"A": ScheduledSignal("A", 1)},
        risk_limits=portfolio_limits(
            risk_per_trade=D("0.06"),
            max_open_risk=D("0.18"),
            max_correlated_risk=D("0.12"),
        ),
        risk_taper=True,
    )
    result = engine.run(
        {"A": data("A")},
        BacktestConfig(cost_preset=CostPreset.ZERO, bar_interval="1h"),
    )
    decision = next(event for event in result.audit_trail if event.event_type == "RISK_DECISION")
    assert decision.details["approved"] is True
    assert decision.details["risk_fraction"] == "0.04"


def test_portfolio_fingerprint_covers_all_outcome_inputs() -> None:
    source = data("A")
    base_instrument = market("A", "A")
    base_limits = portfolio_limits()

    def run_fingerprint(
        *,
        selected_instrument: Instrument | None = None,
        selected_strategy: Strategy | None = None,
        selected_limits: RiskLimits | None = None,
        selected_bars: tuple[Bar, ...] | None = None,
        config: BacktestConfig | None = None,
        cost_model: CostModel | None = None,
    ) -> str:
        engine = PortfolioBacktestEngine(
            {"A": selected_instrument or base_instrument},
            {"A": selected_strategy or ScheduledSignal("A", 1)},
            risk_limits=selected_limits or base_limits,
            cost_models={} if cost_model is None else {"A": cost_model},
        )
        return engine.run(
            {"A": selected_bars or source},
            config or BacktestConfig(bar_interval="1h"),
        ).run_fingerprint

    baseline = run_fingerprint()
    config_variants = (
        BacktestConfig(starting_equity=D("600"), bar_interval="1h"),
        BacktestConfig(execution_delay_bars=2, bar_interval="1h"),
        BacktestConfig(maximum_holding_bars=1, bar_interval="1h"),
        BacktestConfig(operational_costs=D("1"), bar_interval="1h"),
        BacktestConfig(seed=99, bar_interval="1h"),
        BacktestConfig(close_positions_at_end=False, bar_interval="1h"),
        BacktestConfig(cost_preset=CostPreset.STRESSED, bar_interval="1h"),
    )
    for config in config_variants:
        assert run_fingerprint(config=config) != baseline

    changed_volume = (replace(source[0], volume=D("123")), *source[1:])
    changed_quality = (replace(source[0], data_quality=D("0.99")), *source[1:])
    assert run_fingerprint(selected_bars=changed_volume) != baseline
    assert run_fingerprint(selected_bars=changed_quality) != baseline
    assert (
        run_fingerprint(selected_instrument=replace(base_instrument, contract_size=D("2")))
        != baseline
    )
    assert (
        run_fingerprint(selected_limits=replace(base_limits, max_daily_loss=D("0.04"))) != baseline
    )
    assert (
        run_fingerprint(selected_strategy=ScheduledSignal("A", 1, probability="0.61")) != baseline
    )
    assert run_fingerprint(cost_model=CostModel.from_preset(CostPreset.OPTIMISTIC)) != baseline


def test_portfolio_fingerprint_covers_simulator_behavior_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = PortfolioBacktestEngine(
        {"A": market("A", "A")},
        {"A": ScheduledSignal("A", 1)},
        risk_limits=portfolio_limits(),
    )
    source = {"A": data("A")}
    config = BacktestConfig(bar_interval="1h")
    baseline = engine.run(source, config).run_fingerprint

    monkeypatch.setattr(
        portfolio_engine_module,
        "SIMULATOR_BEHAVIOR_VERSION",
        "historical-simulator-test-version",
    )

    assert engine.run(source, config).run_fingerprint != baseline
