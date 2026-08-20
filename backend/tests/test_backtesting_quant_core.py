from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.backtesting import Bar, FillPolicy
from app.backtesting.engine import BacktestConfig, HistoricalBacktestEngine
from app.backtesting.models import ExitReason
from app.challenger import ChallengeContext, DeterministicChallenger
from app.core.clock import SimulationClock
from app.instruments.models import AssetClass, Instrument
from app.opportunities import Direction, ExpectedGrowthScorer, OpportunityCandidate
from app.portfolio import ManagedCapitalLedger, OpenExposure, PortfolioRiskState
from app.regimes import Regime, RegimeDetector
from app.risk import RiskEngine, RiskLimits, StrategyHealth
from app.strategies.base import Strategy
from app.strategies.trend_breakout import TrendBreakoutStrategy

D = Decimal
UTC = UTC


def make_instrument() -> Instrument:
    return Instrument(
        "X",
        "X",
        AssetClass.INDEX,
        point_value=D("1"),
        min_deal_size=D("0.01"),
        size_step=D("0.01"),
        margin_factor=D("0.01"),
        correlation_cluster="US_EQUITY",
    )


def make_candidate(ts: datetime, direction: Direction = Direction.LONG) -> OpportunityCandidate:
    return OpportunityCandidate(
        timestamp=ts,
        instrument_id="X",
        strategy_version_id="fixed-v1",
        direction=direction,
        signal_price=D("100"),
        expected_horizon=timedelta(hours=2),
        raw_signal_score=D("0.8"),
        calibrated_probability=D("0.6"),
        expected_upside=D("0.05"),
        expected_downside=D("0.05"),
        reward_risk_ratio=D("1.5"),
        historical_support=100,
        proposed_stop_distance=D("5"),
        proposed_target_distance=D("5"),
        correlation_cluster="US_EQUITY",
    )


class FixedStrategy(Strategy):
    version_id = "fixed-v1"

    def __init__(self, direction: Direction = Direction.LONG) -> None:
        self.direction = direction

    def evaluate(self, view):
        return (
            make_candidate(view.latest.timestamp, self.direction) if len(view.bars) == 1 else None
        )


def limits() -> RiskLimits:
    return RiskLimits(
        min_reward_risk=D("0.5"),
        max_market_exposure=D("10"),
        max_effective_leverage=D("10"),
        max_margin_usage=D("1"),
    )


def bars_for_exit(high: str, low: str, *, second_open: str = "100") -> tuple[Bar, ...]:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    return (
        Bar(start, D("100"), D("101"), D("99"), D("100"), instrument_id="X"),
        Bar(
            start + timedelta(hours=1),
            D(second_open),
            D(high),
            D(low),
            D(second_open),
            instrument_id="X",
        ),
        Bar(start + timedelta(hours=2), D("100"), D("101"), D("99"), D("100"), instrument_id="X"),
    )


def test_next_bar_entry_and_long_winner() -> None:
    bars = bars_for_exit("106", "99")
    result = HistoricalBacktestEngine(make_instrument(), FixedStrategy(), risk_limits=limits()).run(
        bars, BacktestConfig(cost_preset="ZERO", bar_interval="1h")
    )
    assert result.trades[0].entry_timestamp == bars[0].timestamp
    assert result.trades[0].exit_reason is ExitReason.TARGET
    assert result.trades[0].gross_pnl == D("10.00")


def test_short_winner_and_short_loser_accounting() -> None:
    winner = HistoricalBacktestEngine(
        make_instrument(), FixedStrategy(Direction.SHORT), risk_limits=limits()
    ).run(
        bars_for_exit("101", "94"),
        BacktestConfig(cost_preset="ZERO", bar_interval="1h"),
    )
    loser = HistoricalBacktestEngine(
        make_instrument(), FixedStrategy(Direction.SHORT), risk_limits=limits()
    ).run(
        bars_for_exit("106", "99"),
        BacktestConfig(cost_preset="ZERO", bar_interval="1h"),
    )
    assert winner.trades[0].gross_pnl == D("10.00")
    assert loser.trades[0].gross_pnl == D("-10.00")


def test_conservative_intrabar_ambiguity_chooses_stop() -> None:
    bars = bars_for_exit("106", "94")
    engine = HistoricalBacktestEngine(make_instrument(), FixedStrategy(), risk_limits=limits())
    conservative = engine.run(
        bars,
        BacktestConfig(
            cost_preset="ZERO",
            fill_policy=FillPolicy.CONSERVATIVE,
            bar_interval="1h",
        ),
    )
    target_first = engine.run(
        bars,
        BacktestConfig(
            cost_preset="ZERO",
            fill_policy=FillPolicy.TARGET_FIRST,
            bar_interval="1h",
        ),
    )
    assert conservative.trades[0].exit_reason is ExitReason.STOP
    assert conservative.trades[0].net_pnl == D("-10.00")
    assert target_first.trades[0].exit_reason is ExitReason.TARGET
    assert target_first.trades[0].net_pnl == D("10.00")


def test_gap_beyond_stop_fills_at_worse_open() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    bars = (
        Bar(start, D("100"), D("101"), D("99"), D("100"), instrument_id="X"),
        Bar(start + timedelta(hours=1), D("100"), D("102"), D("98"), D("100"), instrument_id="X"),
        Bar(start + timedelta(hours=2), D("90"), D("91"), D("89"), D("90"), instrument_id="X"),
    )
    result = HistoricalBacktestEngine(make_instrument(), FixedStrategy(), risk_limits=limits()).run(
        bars, BacktestConfig(cost_preset="ZERO", bar_interval="1h")
    )
    assert result.trades[0].exit_reason is ExitReason.STOP
    assert result.trades[0].requested_exit == D("90")
    assert result.trades[0].net_pnl == D("-20.00")


def test_candidate_growth_score_is_geometric_and_inspectable() -> None:
    candidate = make_candidate(datetime(2024, 1, 1, tzinfo=UTC))
    score = ExpectedGrowthScorer().score(candidate)
    assert score.expected_log_growth != D("0")
    assert score.total == (
        score.expected_log_growth
        * score.confidence_factor
        * score.regime_factor
        * score.data_quality_factor
        * score.strategy_health_factor
        - score.cost_penalty
        - score.tail_risk_penalty
        - score.correlation_penalty
        - score.event_risk_penalty
        - score.uncertainty_penalty
    )


def test_deterministic_challenger_rejects_stale_and_poor_rr() -> None:
    ts = datetime(2024, 1, 1, tzinfo=UTC)
    weak = replace(make_candidate(ts), reward_risk_ratio=D("0.5"))
    result = DeterministicChallenger().challenge(
        weak,
        ChallengeContext(now=ts + timedelta(hours=3)),
    )
    assert not result.approved
    assert len(result.rejection_reasons) == 2
    assert "stale_signal" in result.penalties
    assert "reward_risk" in result.penalties


def test_correlation_and_suspended_strategy_fail_closed() -> None:
    ts = datetime(2024, 1, 1, tzinfo=UTC)
    candidate = make_candidate(ts)
    portfolio = PortfolioRiskState(
        positions=(
            OpenExposure(
                "Y",
                Direction.LONG,
                D("19"),
                D("100"),
                D("5"),
                "US_EQUITY",
            ),
        )
    )
    risk = RiskEngine(limits())
    suspended = risk.evaluate(
        candidate,
        make_instrument(),
        ManagedCapitalLedger(),
        portfolio,
        strategy_health=StrategyHealth.SUSPENDED,
        now=ts,
    )
    assert not suspended.approved
    assert any("SUSPENDED" in reason for reason in suspended.reasons)
    assert "maximum correlated exposure exceeded" in suspended.reasons


def test_regime_detector_and_trend_strategy_use_completed_history() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    bars = []
    for index in range(120):
        close = D("100") + D(index)
        bars.append(
            Bar(
                start + timedelta(hours=index),
                close - D("0.5"),
                close + D("0.4"),
                close - D("0.6"),
                close,
                instrument_id="X",
            )
        )
    regime = RegimeDetector().detect(bars)
    assert regime.trend is Regime.TRENDING_UP
    assert regime == RegimeDetector().detect(bars[-65:])
    clock = SimulationClock(bars[-1].timestamp)
    from app.backtesting.data_guard import GuardedBarSeries, MarketView
    from app.strategies.trend_breakout import TrendBreakoutConfig

    opportunity = TrendBreakoutStrategy(
        config=TrendBreakoutConfig(maximum_extension_atr=D("20"))
    ).evaluate(MarketView(make_instrument(), GuardedBarSeries(bars, clock)))
    assert opportunity is not None
    assert opportunity.direction is Direction.LONG
    assert opportunity.timestamp == bars[-1].timestamp
    assert opportunity.calibrated_probability is None
    assert opportunity.historical_support == len(bars) - 65

    scored = opportunity.with_growth_score(ExpectedGrowthScorer().score(opportunity))
    challenge = DeterministicChallenger().challenge(
        scored,
        ChallengeContext(now=bars[-1].timestamp),
    )
    assert challenge.approved
    assert "historical support is sufficient" in challenge.supporting_factors
