from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.backtesting import Bar, MarketView
from app.backtesting.costs import CostModel, CostPreset
from app.backtesting.engine import BacktestConfig, HistoricalBacktestEngine
from app.backtesting.metrics import calculate_metrics
from app.backtesting.models import EquityPoint, ExitReason
from app.core.decimal import money
from app.instruments.models import AssetClass, Instrument
from app.opportunities import Direction, OpportunityCandidate
from app.portfolio import ManagedCapitalLedger, PortfolioRiskState
from app.risk import (
    BreakerKind,
    CircuitBreakerRegistry,
    PositionSizer,
    PositionSizingRequest,
    RiskEngine,
    RiskLimits,
)
from app.risk.taper import RiskBand, RiskTaper
from app.strategies.base import Strategy

D = Decimal


def leveraged_instrument(*, minimum: str = "0.01") -> Instrument:
    return Instrument(
        "FX",
        "FX",
        AssetClass.FX,
        point_value=D("2"),
        contract_size=D("3"),
        min_deal_size=D(minimum),
        size_step=D("0.01"),
        margin_factor=D("0.10"),
        currency_conversion=D("1.5"),
    )


def test_point_value_contract_fx_margin_and_size_are_exact_decimals() -> None:
    result = PositionSizer().calculate(
        PositionSizingRequest(
            equity=D("500"),
            risk_fraction=D("0.02"),
            entry_price=D("100"),
            stop_distance=D("2"),
            instrument=leveraged_instrument(),
        )
    )
    # £18 loss per unit = 2 points x £2/point x 3 contract x 1.5 FX.
    assert result.loss_per_unit == D("18.0")
    assert result.size == D("0.55")
    assert result.actual_risk == D("9.90")
    assert result.notional == D("247.50")
    assert result.margin_required == D("24.75")


def test_minimum_deal_size_is_rejected_when_its_stop_loss_exceeds_budget() -> None:
    result = PositionSizer().calculate(
        PositionSizingRequest(
            equity=D("500"),
            risk_fraction=D("0.02"),
            entry_price=D("100"),
            stop_distance=D("2"),
            instrument=leveraged_instrument(minimum="1"),
        )
    )
    assert not result.accepted
    assert result.actual_risk == D("18.00")
    assert result.reason == "minimum deal size exceeds permitted monetary risk"


class HoldStrategy(Strategy):
    version_id = "hold-v1"

    def evaluate(self, view: MarketView) -> OpportunityCandidate | None:
        if len(view.bars) != 1:
            return None
        bar = view.latest
        return OpportunityCandidate(
            timestamp=bar.timestamp,
            instrument_id="COST",
            strategy_version_id=self.version_id,
            direction=Direction.LONG,
            signal_price=bar.close,
            expected_horizon=timedelta(days=2),
            raw_signal_score=D("0.8"),
            calibrated_probability=D("0.6"),
            expected_upside=D("0.20"),
            expected_downside=D("0.05"),
            reward_risk_ratio=D("4"),
            historical_support=100,
            proposed_stop_distance=D("5"),
            proposed_target_distance=D("20"),
        )


def test_cost_components_are_booked_but_unrequested_guaranteed_stop_is_not() -> None:
    instrument = Instrument(
        "COST",
        "Cost market",
        AssetClass.INDEX,
        min_deal_size=D("0.01"),
        size_step=D("0.01"),
        margin_factor=D("0.01"),
    )
    start = datetime(2024, 1, 1, tzinfo=UTC)
    bars = (
        Bar(start, D("100"), D("101"), D("99"), D("100"), instrument_id="COST"),
        Bar(
            start + timedelta(days=1),
            D("100"),
            D("102"),
            D("99"),
            D("101"),
            instrument_id="COST",
        ),
        Bar(
            start + timedelta(days=2),
            D("101"),
            D("103"),
            D("100"),
            D("102"),
            instrument_id="COST",
        ),
    )
    cost_model = CostModel(
        preset=CostPreset.REALISTIC,
        spread_bps=D("2"),
        slippage_bps_per_side=D("1"),
        commission_bps_per_side=D("1"),
        financing_bps_per_day=D("2"),
        guaranteed_stop_premium_bps=D("1"),
        currency_conversion_bps=D("100"),
    )
    result = HistoricalBacktestEngine(
        instrument,
        HoldStrategy(),
        cost_model=cost_model,
        risk_limits=RiskLimits(
            min_reward_risk=D("1"),
            max_market_exposure=D("5"),
            max_effective_leverage=D("5"),
            max_margin_usage=D("1"),
        ),
    ).run(bars, BacktestConfig(maximum_holding_bars=2))
    trade = result.trades[0]
    assert trade.exit_reason is ExitReason.TIME
    assert trade.holding_seconds == 172800
    assert trade.spread_cost > D("0")
    assert trade.slippage_cost > D("0")
    assert trade.financing_cost > D("0")
    assert trade.financing_cost == money(trade.fill_notional * D("2") / D("10000") * D("2"))
    assert trade.commission > D("0")
    # Ordinary simulated stops are not guaranteed; the proxy is not charged.
    assert trade.guaranteed_stop_premium == D("0")
    assert trade.currency_conversion_cost > D("0")
    assert trade.net_pnl == trade.gross_pnl - trade.total_cost


def test_milestones_and_fallback_below_target_are_reported() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    curve = (
        EquityPoint(start, D("500"), D("500"), D("0")),
        EquityPoint(start + timedelta(days=1), D("760"), D("760"), D("0")),
        EquityPoint(
            start + timedelta(days=2),
            D("740"),
            D("760"),
            D("20") / D("760"),
        ),
        EquityPoint(start + timedelta(days=3), D("1005"), D("1005"), D("0")),
    )
    metrics = calculate_metrics(D("500"), (), curve)
    assert metrics.milestones["750"].first_exceeded == curve[1].timestamp
    assert metrics.milestones["750"].fell_below_after
    assert metrics.milestones["1000"].first_exceeded == curve[3].timestamp
    assert metrics.milestones["2500"].first_exceeded is None


def test_operational_cost_is_a_consistent_final_equity_deduction() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    curve = (
        EquityPoint(start, D("500"), D("500"), D("0")),
        EquityPoint(start + timedelta(days=365), D("800"), D("800"), D("0")),
    )
    metrics = calculate_metrics(D("500"), (), curve, operational_costs=D("60"))
    assert metrics.final_equity_before_operational_costs == D("800.00")
    assert metrics.final_equity == D("740.00")
    assert metrics.trading_return_before_operational_costs == D("0.6")
    assert metrics.trading_return_after_operational_costs == D("0.48")
    assert metrics.total_return == D("0.48")
    assert metrics.cagr is not None and metrics.cagr < D("0.60")
    assert metrics.maximum_drawdown == D("0.075")
    assert metrics.milestones["750"].first_exceeded == curve[-1].timestamp
    assert metrics.milestones["750"].fell_below_after


def test_daily_weekly_rolling_and_total_drawdown_breakers_fail_closed() -> None:
    timestamp = datetime(2024, 1, 1, tzinfo=UTC)
    ledger = ManagedCapitalLedger(D("500"))
    ledger.post_trade("loss", D("-160"), timestamp=timestamp)
    candidate = OpportunityCandidate(
        timestamp=timestamp,
        instrument_id="COST",
        strategy_version_id="risk-v1",
        direction=Direction.LONG,
        signal_price=D("100"),
        expected_horizon=timedelta(hours=1),
        raw_signal_score=D("0.8"),
        calibrated_probability=D("0.6"),
        expected_upside=D("0.10"),
        expected_downside=D("0.05"),
        reward_risk_ratio=D("2"),
        historical_support=100,
        proposed_stop_distance=D("5"),
    )
    portfolio = PortfolioRiskState(
        daily_loss=D("30"),
        weekly_loss=D("60"),
        peak_equity=D("500"),
    )
    instrument = Instrument("COST", "Cost", AssetClass.INDEX)
    risk = RiskEngine(RiskLimits(max_market_exposure=D("5")))
    decision = risk.evaluate(candidate, instrument, ledger, portfolio, now=timestamp)
    assert not decision.approved
    reasons = " ".join(decision.reasons)
    assert "daily loss" in reasons
    assert "weekly loss" in reasons
    assert "rolling drawdown" in reasons
    assert "total drawdown" in reasons


def _period_test_candidate(timestamp: datetime) -> OpportunityCandidate:
    return OpportunityCandidate(
        timestamp=timestamp,
        instrument_id="PERIOD",
        strategy_version_id="period-v1",
        direction=Direction.LONG,
        signal_price=D("100"),
        expected_horizon=timedelta(hours=1),
        raw_signal_score=D("0.8"),
        calibrated_probability=D("0.6"),
        expected_upside=D("0.10"),
        expected_downside=D("0.05"),
        reward_risk_ratio=D("2"),
        historical_support=100,
        proposed_stop_distance=D("5"),
    )


def _period_test_risk_engine() -> tuple[RiskEngine, Instrument, ManagedCapitalLedger]:
    limits = RiskLimits(
        min_reward_risk=D("1"),
        max_market_exposure=D("5"),
        max_effective_leverage=D("5"),
        max_margin_usage=D("1"),
    )
    instrument = Instrument("PERIOD", "Period market", AssetClass.INDEX)
    return RiskEngine(limits), instrument, ManagedCapitalLedger(D("500"))


def test_daily_loss_breaker_resets_on_next_utc_day() -> None:
    first_day = datetime(2024, 1, 4, 23, 30, tzinfo=UTC)
    next_day = datetime(2024, 1, 5, 0, 30, tzinfo=UTC)
    risk, instrument, ledger = _period_test_risk_engine()

    blocked = risk.evaluate(
        _period_test_candidate(first_day),
        instrument,
        ledger,
        PortfolioRiskState(daily_loss=D("30")),
        now=first_day,
    )
    assert not blocked.approved
    assert BreakerKind.DAILY_LOSS in {event.kind for event in risk.breakers.active}

    resumed = risk.evaluate(
        _period_test_candidate(next_day),
        instrument,
        ledger,
        PortfolioRiskState(),
        now=next_day,
    )
    assert resumed.approved
    assert BreakerKind.DAILY_LOSS not in {event.kind for event in risk.breakers.active}


def test_weekly_loss_breaker_resets_on_next_iso_week() -> None:
    first_week = datetime(2024, 1, 5, 12, tzinfo=UTC)
    next_week = datetime(2024, 1, 8, 12, tzinfo=UTC)
    risk, instrument, ledger = _period_test_risk_engine()

    blocked = risk.evaluate(
        _period_test_candidate(first_week),
        instrument,
        ledger,
        PortfolioRiskState(weekly_loss=D("60")),
        now=first_week,
    )
    assert not blocked.approved
    assert BreakerKind.WEEKLY_LOSS in {event.kind for event in risk.breakers.active}

    resumed = risk.evaluate(
        _period_test_candidate(next_week),
        instrument,
        ledger,
        PortfolioRiskState(),
        now=next_week,
    )
    assert resumed.approved
    assert BreakerKind.WEEKLY_LOSS not in {event.kind for event in risk.breakers.active}


def test_period_reset_keeps_total_drawdown_and_other_hard_breakers_latched() -> None:
    registry = CircuitBreakerRegistry()
    tripped_at = datetime(2024, 1, 5, 12, tzinfo=UTC)
    registry.trip(BreakerKind.DAILY_LOSS, "daily", tripped_at)
    registry.trip(BreakerKind.WEEKLY_LOSS, "weekly", tripped_at)
    registry.trip(BreakerKind.TOTAL_DRAWDOWN, "total", tripped_at)
    registry.trip(BreakerKind.STRATEGY_EXCEPTION, "strategy", tripped_at)

    daily_expired = registry.reset_expired_periods(datetime(2024, 1, 6, 12, tzinfo=UTC))
    assert daily_expired == (BreakerKind.DAILY_LOSS,)
    assert {event.kind for event in registry.active} == {
        BreakerKind.WEEKLY_LOSS,
        BreakerKind.TOTAL_DRAWDOWN,
        BreakerKind.STRATEGY_EXCEPTION,
    }

    weekly_expired = registry.reset_expired_periods(datetime(2024, 1, 8, 12, tzinfo=UTC))

    assert weekly_expired == (BreakerKind.WEEKLY_LOSS,)
    assert {event.kind for event in registry.active} == {
        BreakerKind.TOTAL_DRAWDOWN,
        BreakerKind.STRATEGY_EXCEPTION,
    }


def test_risk_taper_reduces_fraction_as_equity_grows() -> None:
    taper = RiskTaper.research_default()
    assert taper.fraction_for(D("500")) == D("0.04")
    assert taper.fraction_for(D("1500")) == D("0.03")
    assert taper.fraction_for(D("3000")) == D("0.02")
    assert taper.fraction_for(D("4500")) == D("0.01")


def test_risk_engine_taper_caps_successive_sizing_from_current_equity() -> None:
    timestamp = datetime(2024, 1, 1, tzinfo=UTC)
    taper = RiskTaper(
        (
            RiskBand(D("0"), D("550"), D("0.04")),
            RiskBand(D("550"), None, D("0.02")),
        )
    )
    limits = RiskLimits(
        risk_per_trade=D("0.06"),
        max_open_risk=D("0.18"),
        max_market_exposure=D("10"),
        max_effective_leverage=D("10"),
        max_margin_usage=D("1"),
        max_correlated_risk=D("0.12"),
        min_reward_risk=D("1"),
    )
    instrument = Instrument(
        "TAPER",
        "Taper market",
        AssetClass.INDEX,
        min_deal_size=D("0.01"),
        size_step=D("0.01"),
    )

    def opportunity(at: datetime) -> OpportunityCandidate:
        return OpportunityCandidate(
            timestamp=at,
            instrument_id="TAPER",
            strategy_version_id="taper-v1",
            direction=Direction.LONG,
            signal_price=D("100"),
            expected_horizon=timedelta(hours=1),
            raw_signal_score=D("0.8"),
            calibrated_probability=D("0.6"),
            expected_upside=D("0.10"),
            expected_downside=D("0.05"),
            reward_risk_ratio=D("2"),
            historical_support=100,
            proposed_stop_distance=D("5"),
            requested_risk_fraction=D("0.06"),
        )

    ledger = ManagedCapitalLedger(D("500"))
    risk = RiskEngine(limits, risk_taper=taper)
    first = risk.evaluate(opportunity(timestamp), instrument, ledger, now=timestamp)
    assert first.approved
    assert first.equity_basis == D("500.00")
    assert first.risk_fraction == D("0.04")
    assert first.permitted_risk == D("20.00")
    assert first.position_size == D("4.00")

    ledger.post_trade("realised-win", D("100"), timestamp=timestamp + timedelta(hours=1))
    second_time = timestamp + timedelta(hours=2)
    second = risk.evaluate(opportunity(second_time), instrument, ledger, now=second_time)
    assert second.approved
    assert second.equity_basis == D("600.00")
    assert second.risk_fraction == D("0.02")
    assert second.permitted_risk == D("12.00")
    assert second.position_size == D("2.40")
