from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from app.backtesting import (
    Bar,
    ConversionBoundary,
    ConversionStalenessPolicy,
    ConversionUnavailableError,
    MarketView,
    QuoteToGbpConversionPolicy,
    ResearchCostAssumption,
    ResearchCostSchedule,
)
from app.backtesting.costs import CostModel, CostPreset
from app.backtesting.engine import BacktestConfig, HistoricalBacktestEngine
from app.backtesting.fill_revalidation import FillRiskRevalidationPolicy
from app.backtesting.fingerprint import SIMULATOR_BEHAVIOR_VERSION
from app.backtesting.portfolio_engine import PortfolioBacktestEngine
from app.backtesting.research_costs import apply_research_cost_assumption
from app.core.decimal import money
from app.instruments import AssetClass, Instrument
from app.instruments.catalog import CORE_UNIVERSE
from app.opportunities import Direction, OpportunityCandidate
from app.risk import PositionSizer, PositionSizingRequest, RiskLimits
from app.strategies import Strategy

D = Decimal


def _bar(timestamp: datetime, price: str, instrument_id: str) -> Bar:
    close = D(price)
    delta = min(D("1"), close / D("10"))
    return Bar(
        timestamp,
        close,
        close + delta,
        close - delta,
        close,
        instrument_id=instrument_id,
    )


def _instrument(
    instrument_id: str,
    *,
    quote_currency: str = "GBP",
    asset_class: AssetClass = AssetClass.INDEX,
) -> Instrument:
    return Instrument(
        instrument_id,
        instrument_id,
        asset_class,
        quote_currency=quote_currency,
        min_deal_size=D("0.01"),
        size_step=D("0.01"),
        margin_factor=D("0.01"),
    )


def _limits() -> RiskLimits:
    return RiskLimits(
        min_reward_risk=D("1"),
        max_market_exposure=D("10"),
        max_effective_leverage=D("10"),
        max_margin_usage=D("1"),
    )


class _OneSignal(Strategy):
    def __init__(
        self,
        instrument_id: str,
        *,
        probability: str = "0.60",
        target_distance: str = "5",
        visible_count: int = 1,
    ) -> None:
        self.instrument_id = instrument_id
        self.probability = D(probability)
        self.target_distance = D(target_distance)
        self.visible_count = visible_count
        self.version_id = f"realism-v1:{instrument_id}"

    def evaluate(self, view: MarketView) -> OpportunityCandidate | None:
        if len(view.bars) != self.visible_count:
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
            expected_upside=D("0.10"),
            expected_downside=D("0.05"),
            reward_risk_ratio=D("2"),
            historical_support=100,
            proposed_stop_distance=D("5"),
            proposed_target_distance=self.target_distance,
        )


class _NoSignal(Strategy):
    version_id = "no-signal-v1"

    def evaluate(self, view: MarketView) -> None:
        del view
        return None


def test_causal_conversion_paths_use_completed_bars_only() -> None:
    timestamp = datetime(2025, 1, 6, 12, tzinfo=UTC)
    resolver = QuoteToGbpConversionPolicy.causal().build(
        {
            "GBPUSD": (_bar(timestamp, "2", "GBPUSD"),),
            "EURGBP": (_bar(timestamp, "0.85", "EURGBP"),),
            "USDJPY": (_bar(timestamp, "100", "USDJPY"),),
        },
        interval="1h",
    )

    assert resolver.resolve("GBP", as_of=timestamp).rate_to_gbp == D("1")
    assert resolver.resolve("USD", as_of=timestamp).rate_to_gbp == D("0.5")
    assert resolver.resolve("EUR", as_of=timestamp).rate_to_gbp == D("0.85")
    assert resolver.resolve("JPY", as_of=timestamp).rate_to_gbp == D("0.005")


def test_strict_boundary_ignores_same_timestamp_cross_rate_spike() -> None:
    earlier = datetime(2025, 1, 6, 11, tzinfo=UTC)
    execution = earlier + timedelta(hours=1)
    resolver = QuoteToGbpConversionPolicy.causal().build(
        {
            "GBPUSD": (
                _bar(earlier, "2", "GBPUSD"),
                _bar(execution, "4", "GBPUSD"),
            )
        },
        interval="1h",
    )

    strict = resolver.resolve(
        "USD",
        as_of=execution,
        boundary=ConversionBoundary.STRICTLY_BEFORE,
    )
    inclusive = resolver.resolve(
        "USD",
        as_of=execution,
        boundary=ConversionBoundary.AT_OR_BEFORE,
    )
    assert strict.rate_to_gbp == D("0.5")
    assert strict.legs[0].observed_at == earlier
    assert inclusive.rate_to_gbp == D("0.25")


def test_conversion_resolution_is_independent_of_input_mapping_order() -> None:
    timestamp = datetime(2025, 1, 6, 12, tzinfo=UTC)
    bars = {
        "GBPUSD": (_bar(timestamp, "2", "GBPUSD"),),
        "USDJPY": (_bar(timestamp, "100", "USDJPY"),),
    }
    forward = QuoteToGbpConversionPolicy.causal().build(bars, interval="1h")
    reversed_order = QuoteToGbpConversionPolicy.causal().build(
        dict(reversed(tuple(bars.items()))), interval="1h"
    )

    assert (
        forward.resolve("JPY", as_of=timestamp).audit_details()
        == reversed_order.resolve("JPY", as_of=timestamp).audit_details()
    )


def test_daily_easter_gap_is_tolerated_but_older_conversion_fails_closed() -> None:
    observed = datetime(2025, 4, 17, 23, tzinfo=UTC)
    resolver = QuoteToGbpConversionPolicy.causal().build(
        {"GBPUSD": (_bar(observed, "1.25", "GBPUSD"),)},
        interval="1d",
    )

    easter_reopen = resolver.resolve(
        "USD",
        as_of=datetime(2025, 4, 22, 23, tzinfo=UTC),
        boundary=ConversionBoundary.STRICTLY_BEFORE,
    )
    assert easter_reopen.rate_to_gbp == D("0.8")
    assert easter_reopen.audit_details()["legs"][0]["maximum_age_seconds"] == 604800

    with pytest.raises(ConversionUnavailableError, match="stale"):
        resolver.resolve(
            "USD",
            as_of=datetime(2025, 4, 25, tzinfo=UTC),
            boundary=ConversionBoundary.STRICTLY_BEFORE,
        )


def test_static_rates_exist_only_when_explicitly_selected() -> None:
    timestamp = datetime(2025, 1, 1, tzinfo=UTC)
    causal = QuoteToGbpConversionPolicy.causal().build({}, interval="1d")
    with pytest.raises(ConversionUnavailableError, match="no completed conversion bar"):
        causal.resolve("USD", as_of=timestamp)

    static = QuoteToGbpConversionPolicy.explicit_static({"USD": "0.78"}).build({}, interval="1d")
    quote = static.resolve("USD", as_of=timestamp)
    assert quote.rate_to_gbp == D("0.78")
    assert quote.formula == "explicit configured static rate; no historical quote claim"


def test_research_cost_schedule_is_distinct_conservative_and_not_ig_quotes() -> None:
    schedule = ResearchCostSchedule()
    fx = schedule.assumption_for("GBPUSD")
    gold = schedule.assumption_for("GOLD")
    assert fx.model.spread_bps >= CostModel.from_preset("REALISTIC").spread_bps
    assert fx.model.slippage_bps_per_side >= D("0.5")
    assert fx.model.commission_bps_per_side >= D("0.25")
    assert fx.model.financing_bps_per_day >= D("0.5")
    assert fx.model.guaranteed_stop_premium_bps == D("0")
    assert gold.model != fx.model
    assert fx.audit_details()["historical_ig_quotes"] is False
    assert "proxy" in fx.provenance.lower()

    stressed = schedule.scaled_assumption_for("GBPUSD", "1.5", scenario_id="protocol")
    assert stressed.model.spread_bps == fx.model.spread_bps * D("1.5")
    assert "x1.5" in stressed.assumption_id


def test_candidate_conversion_cost_estimate_is_round_trip_per_side() -> None:
    candidate = OpportunityCandidate(
        timestamp=datetime(2025, 1, 6, 15, tzinfo=UTC),
        instrument_id="USD-MARKET",
        strategy_version_id="cost-estimate-v1",
        direction=Direction.LONG,
        signal_price=D("100"),
        expected_horizon=timedelta(days=1),
        raw_signal_score=D("0.7"),
        calibrated_probability=D("0.6"),
        expected_upside=D("0.1"),
        expected_downside=D("0.05"),
        reward_risk_ratio=D("2"),
        historical_support=100,
        proposed_stop_distance=D("5"),
        proposed_target_distance=D("10"),
    )
    assumption = ResearchCostAssumption(
        "USD-MARKET",
        "conversion-only",
        CostModel(
            preset=CostPreset.REALISTIC,
            spread_bps=D("0"),
            slippage_bps_per_side=D("0"),
            commission_bps_per_side=D("0"),
            financing_bps_per_day=D("0"),
            currency_conversion_bps=D("10"),
        ),
    )

    estimated, breakdown = apply_research_cost_assumption(candidate, assumption)

    # The broker charges 10 bps on entry notional and again on exit notional.
    assert breakdown.currency_conversion_fee_fraction == D("0.002")
    assert breakdown.total_fraction == D("0.002")
    assert estimated.estimated_total_cost == D("0.002")
    assert assumption.audit_details()["currency_conversion_fee_bps_per_side"] == "10"


def test_market_specific_forecast_costs_change_cross_market_ranking() -> None:
    start = datetime(2025, 1, 6, 15, tzinfo=UTC)
    instruments = {key: _instrument(key) for key in ("A", "B")}
    strategies = {
        "A": _OneSignal("A", probability="0.65"),
        "B": _OneSignal("B", probability="0.60"),
    }
    high_cost = CostModel(
        spread_bps=D("0"),
        slippage_bps_per_side=D("0"),
        commission_bps_per_side=D("100"),
        financing_bps_per_day=D("0"),
    )
    zero_cost = CostModel.from_preset(CostPreset.ZERO)
    assumptions = {
        "A": ResearchCostAssumption("A", "high-cost", high_cost),
        "B": ResearchCostAssumption("B", "zero-cost", zero_cost),
    }
    bars = {
        key: tuple(_bar(start + timedelta(hours=index), "100", key) for index in range(3))
        for key in instruments
    }

    result = PortfolioBacktestEngine(
        instruments,
        strategies,
        risk_limits=_limits(),
        cost_assumptions=assumptions,
    ).run(bars, BacktestConfig(cost_preset="ZERO", bar_interval="1h"))

    ranking = next(event for event in result.audit_trail if event.event_type == "CANDIDATES_RANKED")
    assert ranking.details["ranking"][0]["instrument_id"] == "B"
    created = {
        event.details["instrument_id"]: event.details
        for event in result.audit_trail
        if event.event_type == "CANDIDATE_CREATED"
    }
    assert D(str(created["A"]["raw_score"])) > D(str(created["B"]["raw_score"]))
    assert D(str(created["A"]["estimated_total_cost"])) > D(
        str(created["B"]["estimated_total_cost"])
    )
    assert created["A"]["effective_cost_assumption"]["assumption_id"] == "high-cost"


def test_usd_open_fill_and_intrabar_exit_ignore_same_timestamp_fx_spike() -> None:
    start = datetime(2025, 1, 6, 10, tzinfo=UTC)
    trading = (
        _bar(start, "100", "X"),
        Bar(
            start + timedelta(hours=1),
            D("100"),
            D("106"),
            D("99"),
            D("100"),
            instrument_id="X",
        ),
    )

    def run(spike: str):
        references = {
            "GBPUSD": (
                _bar(start - timedelta(hours=1), "2", "GBPUSD"),
                _bar(start, "2", "GBPUSD"),
                _bar(start + timedelta(hours=1), spike, "GBPUSD"),
            )
        }
        return HistoricalBacktestEngine(
            _instrument("X", quote_currency="USD"),
            _OneSignal("X"),
            risk_limits=_limits(),
            cost_model=CostModel.from_preset("ZERO"),
        ).run(
            trading,
            BacktestConfig(cost_preset="ZERO", bar_interval="1h"),
            reference_bars_by_instrument=references,
        )

    normal = run("2")
    spiked = run("4")
    assert normal.trades[0].gross_pnl == spiked.trades[0].gross_pnl == D("10.00")
    assert normal.trades[0].quantity == spiked.trades[0].quantity == D("4.00")
    assert spiked.trades[0].approval_currency_conversion == D("0.5")
    assert spiked.trades[0].entry_currency_conversion == D("0.5")
    assert spiked.trades[0].exit_currency_conversion == D("0.5")


def test_asynchronous_fx_close_after_modeled_open_cannot_price_fill_or_exit() -> None:
    signal_at = datetime(2025, 1, 6, 10, 30, tzinfo=UTC)
    execution_completed_at = datetime(2025, 1, 6, 12, 30, tzinfo=UTC)
    trading = (
        _bar(signal_at, "100", "X"),
        Bar(
            execution_completed_at,
            D("100"),
            D("106"),
            D("99"),
            D("100"),
            instrument_id="X",
        ),
    )

    def run(future_close: str):
        references = {
            "GBPUSD": (
                _bar(datetime(2025, 1, 6, 10, tzinfo=UTC), "2", "GBPUSD"),
                _bar(datetime(2025, 1, 6, 12, tzinfo=UTC), future_close, "GBPUSD"),
            )
        }
        return HistoricalBacktestEngine(
            _instrument("X", quote_currency="USD"),
            _OneSignal("X"),
            risk_limits=_limits(),
            cost_model=CostModel.from_preset("ZERO"),
        ).run(
            trading,
            BacktestConfig(cost_preset="ZERO", bar_interval="1h"),
            reference_bars_by_instrument=references,
        )

    normal = run("2")
    perturbed = run("20")
    normal_trade = normal.trades[0]
    perturbed_trade = perturbed.trades[0]
    modeled_open = datetime(2025, 1, 6, 11, 30, tzinfo=UTC)
    assert normal.audit_trail == perturbed.audit_trail
    assert normal_trade == perturbed_trade
    assert normal_trade.entry_timestamp == modeled_open
    assert normal_trade.exit_timestamp == execution_completed_at
    assert normal_trade.holding_seconds == 3600
    assert normal_trade.entry_currency_conversion == D("0.5")
    assert normal_trade.exit_currency_conversion == D("0.5")


def test_short_completion_gap_cannot_move_fill_before_signal_in_either_engine() -> None:
    signal_at = datetime(2025, 1, 6, 10, 30, tzinfo=UTC)
    bars = (
        _bar(signal_at, "100", "X"),
        _bar(datetime(2025, 1, 6, 11, tzinfo=UTC), "100", "X"),
    )
    config = BacktestConfig(
        cost_preset=CostPreset.ZERO,
        bar_interval="1h",
        close_positions_at_end=False,
    )
    single = HistoricalBacktestEngine(
        _instrument("X"),
        _OneSignal("X"),
        risk_limits=_limits(),
        cost_model=CostModel.from_preset(CostPreset.ZERO),
    ).run(bars, config)
    portfolio = PortfolioBacktestEngine(
        {"X": _instrument("X")},
        {"X": _OneSignal("X")},
        risk_limits=_limits(),
        cost_models={"X": CostModel.from_preset(CostPreset.ZERO)},
    ).run({"X": bars}, config)

    for result in (single, portfolio):
        assert result.broker_orders_submitted == 0
        rejection = next(
            event
            for event in result.audit_trail
            if event.event_type == "ORDER_REJECTED_FILL_TIMING"
        )
        assert rejection.details["modeled_entry_at"] == "2025-01-06T10:00:00+00:00"
        assert rejection.details["original_signal_at"] == signal_at.isoformat()
        assert "precede" in rejection.details["reason"]


def test_fill_revalidation_resizes_an_extreme_conversion_gap() -> None:
    signal_at = datetime(2025, 1, 6, 10, 30, tzinfo=UTC)
    execution_completed_at = datetime(2025, 1, 6, 12, 30, tzinfo=UTC)
    trading = (
        _bar(signal_at, "100", "X"),
        Bar(
            execution_completed_at,
            D("100"),
            D("106"),
            D("99"),
            D("100"),
            instrument_id="X",
        ),
    )
    references = {
        "GBPUSD": (
            _bar(datetime(2025, 1, 6, 10, tzinfo=UTC), "2", "GBPUSD"),
            _bar(datetime(2025, 1, 6, 11, 30, tzinfo=UTC), "1", "GBPUSD"),
        )
    }
    result = HistoricalBacktestEngine(
        _instrument("X", quote_currency="USD"),
        _OneSignal("X"),
        risk_limits=_limits(),
        cost_model=CostModel.from_preset("ZERO"),
    ).run(
        trading,
        BacktestConfig(cost_preset="ZERO", bar_interval="1h"),
        reference_bars_by_instrument=references,
    )

    trade = result.trades[0]
    fill = next(event for event in result.audit_trail if event.event_type == "ORDER_FILLED")
    assert D(fill.details["approval_decision"]["position_size"]) == D("4.00")
    assert D(fill.details["revalidated_decision"]["position_size"]) == D("2.00")
    assert D(fill.details["revalidated_decision"]["planned_monetary_risk"]) == D("10.00")
    assert trade.quantity == D("2.00")
    assert trade.approval_planned_risk == D("10.00")
    assert trade.fill_planned_risk == D("10.00")
    assert trade.approval_currency_conversion == D("0.5")
    assert trade.entry_currency_conversion == D("1")
    assert trade.risk_decision_id != trade.fill_risk_decision_id


def test_portfolio_fill_revalidation_ignores_current_completion_close() -> None:
    start = datetime(2025, 1, 6, 10, 30, tzinfo=UTC)
    instruments = {key: _instrument(key) for key in ("A", "B")}
    strategies = {
        "A": _OneSignal("A", target_distance="1000"),
        "B": _OneSignal("B", target_distance="1000", visible_count=2),
    }

    def run(a_completion_close: str):
        close = D(a_completion_close)
        return PortfolioBacktestEngine(
            instruments,
            strategies,
            risk_limits=_limits(),
            cost_models={key: CostModel.from_preset(CostPreset.ZERO) for key in instruments},
        ).run(
            {
                "A": (
                    _bar(start, "100", "A"),
                    _bar(start + timedelta(hours=1), "100", "A"),
                    Bar(
                        start + timedelta(hours=2),
                        D("100"),
                        max(D("101"), close),
                        min(D("99"), close),
                        close,
                        instrument_id="A",
                    ),
                ),
                "B": tuple(_bar(start + timedelta(hours=index), "100", "B") for index in range(3)),
            },
            BacktestConfig(
                cost_preset=CostPreset.ZERO,
                bar_interval="1h",
                close_positions_at_end=False,
            ),
        )

    normal = run("100")
    perturbed = run("50")
    normal_fill = next(
        event
        for event in normal.audit_trail
        if event.event_type == "ORDER_FILLED" and event.details["instrument_id"] == "B"
    )
    perturbed_fill = next(
        event
        for event in perturbed.audit_trail
        if event.event_type == "ORDER_FILLED" and event.details["instrument_id"] == "B"
    )
    assert normal_fill.details == perturbed_fill.details
    assert normal_fill.details["fill_revalidation_policy"]["completion_state_used"] is False


def test_entry_economics_remain_frozen_when_exit_fx_rate_changes() -> None:
    start = datetime(2025, 1, 6, 10, tzinfo=UTC)
    trading = (
        _bar(start, "100", "X"),
        _bar(start + timedelta(hours=1), "100", "X"),
        Bar(
            start + timedelta(hours=2),
            D("100"),
            D("106"),
            D("99"),
            D("100"),
            instrument_id="X",
        ),
    )
    references = {
        "GBPUSD": (
            _bar(start - timedelta(hours=1), "2", "GBPUSD"),
            _bar(start, "2", "GBPUSD"),
            _bar(start + timedelta(hours=1), "4", "GBPUSD"),
            _bar(start + timedelta(hours=2), "4", "GBPUSD"),
        )
    }
    commission_model = CostModel(
        spread_bps=D("0"),
        slippage_bps_per_side=D("0"),
        commission_bps_per_side=D("10"),
        financing_bps_per_day=D("0"),
    )
    result = HistoricalBacktestEngine(
        _instrument("X", quote_currency="USD"),
        _OneSignal("X"),
        risk_limits=_limits(),
        cost_model=commission_model,
    ).run(
        trading,
        BacktestConfig(bar_interval="1h"),
        reference_bars_by_instrument=references,
    )

    trade = result.trades[0]
    assert trade.approval_currency_conversion == D("0.5")
    assert trade.entry_currency_conversion == D("0.5")
    assert trade.exit_currency_conversion == D("0.25")
    entry_commission = money(
        trade.requested_entry * trade.quantity * D("0.5") * D("10") / D("10000")
    )
    exit_commission = money(
        trade.requested_exit * trade.quantity * D("0.25") * D("10") / D("10000")
    )
    assert trade.commission == money(entry_commission + exit_commission)


def test_open_equity_immediately_reflects_incurred_entry_costs() -> None:
    start = datetime(2025, 1, 6, 10, tzinfo=UTC)
    trading = (
        _bar(start, "100", "X"),
        _bar(start + timedelta(hours=1), "100", "X"),
    )
    references = {
        "GBPUSD": (
            _bar(start - timedelta(hours=1), "2", "GBPUSD"),
            _bar(start, "2", "GBPUSD"),
        )
    }
    costs = CostModel(
        spread_bps=D("20"),
        slippage_bps_per_side=D("10"),
        commission_bps_per_side=D("10"),
        financing_bps_per_day=D("0"),
    )
    result = HistoricalBacktestEngine(
        _instrument("X", quote_currency="USD"),
        _OneSignal("X", target_distance="20"),
        risk_limits=_limits(),
        cost_model=costs,
    ).run(
        trading,
        BacktestConfig(bar_interval="1h", close_positions_at_end=False),
        reference_bars_by_instrument=references,
    )

    assert result.trades == ()
    assert result.equity_curve[-1].equity < D("500")
    fill = next(event for event in result.audit_trail if event.event_type == "ORDER_FILLED")
    assert D(str(fill.details["entry_costs"]["spread"])) > D("0")
    assert fill.details["entry_costs"]["guaranteed_stop_premium"] == "0"


def test_open_entry_costs_reduce_equity_basis_for_later_portfolio_sizing() -> None:
    start = datetime(2025, 1, 6, 10, tzinfo=UTC)
    instruments = {key: _instrument(key) for key in ("A", "B")}
    strategies = {
        "A": _OneSignal("A", target_distance="20"),
        "B": _OneSignal("B", target_distance="20", visible_count=2),
    }
    entry_cost_model = CostModel(
        spread_bps=D("20"),
        slippage_bps_per_side=D("10"),
        commission_bps_per_side=D("10"),
        financing_bps_per_day=D("0"),
    )
    assumptions = {
        "A": ResearchCostAssumption("A", "entry-costs", entry_cost_model),
        "B": ResearchCostAssumption("B", "zero-costs", CostModel.from_preset(CostPreset.ZERO)),
    }
    bars = {
        key: tuple(_bar(start + timedelta(hours=index), "100", key) for index in range(3))
        for key in instruments
    }
    result = PortfolioBacktestEngine(
        instruments,
        strategies,
        risk_limits=_limits(),
        cost_assumptions=assumptions,
    ).run(
        bars,
        BacktestConfig(bar_interval="1h", close_positions_at_end=False),
    )

    second = next(
        event
        for event in result.audit_trail
        if event.event_type == "RISK_DECISION" and event.details["instrument_id"] == "B"
    )
    assert D(str(second.details["realised_ledger_equity"])) == D("500.00")
    assert D(str(second.details["equity_basis"])) < D("500.00")


def test_session_policy_rejects_closed_market_before_sizing_or_fill() -> None:
    saturday = datetime(2025, 1, 4, 15, tzinfo=UTC)
    bars = tuple(_bar(saturday + timedelta(hours=index), "100", "SP500") for index in range(3))
    result = HistoricalBacktestEngine(
        _instrument("SP500"),
        _OneSignal("SP500"),
        risk_limits=_limits(),
        cost_model=CostModel.from_preset("ZERO"),
    ).run(bars, BacktestConfig(cost_preset="ZERO", bar_interval="1h"))

    assert result.broker_orders_submitted == 0
    assert any(event.event_type == "CANDIDATE_REJECTED_SESSION" for event in result.audit_trail)
    assert not any(event.event_type == "RISK_DECISION" for event in result.audit_trail)


def test_session_gap_expiry_rejects_an_order_at_fill() -> None:
    start = datetime(2025, 1, 1, 23, tzinfo=UTC)
    bars = (
        _bar(start, "100", "X"),
        _bar(start + timedelta(days=8), "100", "X"),
    )
    result = HistoricalBacktestEngine(
        _instrument("X"),
        _OneSignal("X"),
        risk_limits=_limits(),
        cost_model=CostModel.from_preset("ZERO"),
    ).run(bars, BacktestConfig(cost_preset="ZERO", bar_interval="1d"))

    assert result.broker_orders_submitted == 0
    rejection = next(
        event for event in result.audit_trail if event.event_type == "ORDER_REJECTED_SESSION"
    )
    assert "exceeds research limit" in rejection.details["session"]["reason"]
    assert any(event.event_type == "RISK_DECISION" for event in result.audit_trail)


def test_catalog_minimum_risk_can_exceed_a_500_pound_budget() -> None:
    gold = Instrument.from_definition(CORE_UNIVERSE["GOLD"])
    result = PositionSizer().calculate(
        PositionSizingRequest(
            equity=D("500"),
            risk_fraction=D("0.02"),
            entry_price=D("2500"),
            stop_distance=D("200"),
            instrument=gold,
        )
    )

    assert not result.accepted
    assert result.permitted_risk == D("10.00")
    assert result.actual_risk == D("20.00")
    assert result.reason == "minimum deal size exceeds permitted monetary risk"
    assert gold.size_step == gold.min_deal_size == D("0.1")
    assert "proxy" in gold.economics_provenance.lower()


def test_reference_bars_are_non_tradable_and_all_realism_inputs_are_fingerprinted() -> None:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    bars = tuple(_bar(start + timedelta(days=index), "100", "X") for index in range(2))
    reference = {
        "GBPUSD": tuple(_bar(start + timedelta(days=index), "2", "GBPUSD") for index in range(2))
    }
    base_instrument = _instrument("X")

    def fingerprint(
        instrument: Instrument = base_instrument,
        *,
        refs: dict[str, tuple[Bar, ...]] = reference,
        policy: QuoteToGbpConversionPolicy | None = None,
        fill_policy: FillRiskRevalidationPolicy | None = None,
    ):
        return HistoricalBacktestEngine(
            instrument,
            _NoSignal(),
            conversion_policy=policy,
            fill_revalidation_policy=fill_policy,
            cost_model=CostModel.from_preset("ZERO"),
        ).run(
            bars,
            BacktestConfig(cost_preset="ZERO", bar_interval="1d"),
            reference_bars_by_instrument=refs,
        )

    baseline = fingerprint()
    market_events = [
        event for event in baseline.audit_trail if event.event_type == "MARKET_BAR_COMPLETED"
    ]
    assert len(market_events) == len(bars)
    assert baseline.broker_orders_submitted == 0
    assumptions = next(
        event for event in baseline.audit_trail if event.event_type == "RESEARCH_ASSUMPTIONS"
    )
    assert assumptions.details["simulator_behavior_version"] == SIMULATOR_BEHAVIOR_VERSION
    assert assumptions.details["reference_instruments"] == ["GBPUSD"]

    changed_reference = {
        "GBPUSD": (
            _bar(start, "2", "GBPUSD"),
            _bar(start + timedelta(days=1), "3", "GBPUSD"),
        )
    }
    changed_policy = QuoteToGbpConversionPolicy.causal(
        staleness=ConversionStalenessPolicy(daily_max_age=timedelta(days=8))
    )
    fingerprints = {
        baseline.run_fingerprint,
        fingerprint(refs=changed_reference).run_fingerprint,
        fingerprint(replace(base_instrument, min_deal_size=D("0.02"))).run_fingerprint,
        fingerprint(replace(base_instrument, size_step=D("0.02"))).run_fingerprint,
        fingerprint(replace(base_instrument, contract_size=D("2"))).run_fingerprint,
        fingerprint(policy=changed_policy).run_fingerprint,
        fingerprint(
            fill_policy=FillRiskRevalidationPolicy(policy_id="fill-revalidation-variant")
        ).run_fingerprint,
    }
    assert len(fingerprints) == 7
    assert SIMULATOR_BEHAVIOR_VERSION == "historical-simulator-v4-modeled-open-fx"
