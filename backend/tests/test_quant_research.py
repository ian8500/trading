from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.analytics import Objective, ParameterSearch
from app.backtesting import Bar
from app.backtesting.models import AuditEvent
from app.backtesting.monte_carlo import TradeSequenceMonteCarlo
from app.backtesting.stress import StressScenario, apply_stress
from app.backtesting.walk_forward import (
    TrainingWindowMode,
    WalkForwardAnalyzer,
    WalkForwardConfig,
    WalkForwardSplitter,
)
from app.replay import ReplaySession
from app.risk.health import HealthThresholds, StrategyHealthMonitor
from app.risk.models import StrategyHealth
from app.strategies.registry import (
    PromotionEvidence,
    StrategyRegistry,
    StrategyVersion,
)

D = Decimal
UTC = UTC


def bars(count: int) -> tuple[Bar, ...]:
    start = datetime(2020, 1, 1, tzinfo=UTC)
    return tuple(
        Bar(
            start + timedelta(days=index),
            D("100"),
            D("101"),
            D("99"),
            D("100"),
        )
        for index in range(count)
    )


def test_walk_forward_splits_are_strictly_out_of_sample() -> None:
    source = bars(30)
    config = WalkForwardConfig(10, 5, 5, TrainingWindowMode.ROLLING)
    windows = WalkForwardSplitter(config).split(source)
    assert len(windows) == 4
    assert all(window.train_end == window.test_start for window in windows)
    assert all(
        source[window.train_end - 1].timestamp < source[window.test_start].timestamp
        for window in windows
    )
    result = WalkForwardAnalyzer[dict, float](config).run(
        source,
        lambda training: {"period": len(training)},
        lambda data, parameters: float(len(data) + parameters["period"]),
        lambda value: value,
    )
    assert len(result.folds) == 4


def test_expanding_walk_forward_keeps_original_training_start() -> None:
    windows = WalkForwardSplitter(WalkForwardConfig(10, 5, 5, TrainingWindowMode.EXPANDING)).split(
        bars(30)
    )
    assert all(window.train_start == 0 for window in windows)
    assert [window.train_end for window in windows] == [10, 15, 20, 25]


def test_parameter_search_flags_an_isolated_peak() -> None:
    search = ParameterSearch(Objective.SHARPE)
    result = search.run(
        {"period": [10, 20, 30]},
        lambda params: {"sharpe": 10.0 if params["period"] == 20 else 1.0},
    )
    assert result.best.parameters == {"period": 20}
    assert result.best.isolated_peak


def test_seeded_monte_carlo_is_reproducible_and_reports_targets() -> None:
    returns = (D("0.10"), D("-0.05"), D("0.03"), D("0.02"))
    simulation = TradeSequenceMonteCarlo()
    first = simulation.run(returns, simulations=100, seed=7)
    second = simulation.run(returns, simulations=100, seed=7)
    assert first == second
    assert set(first.target_probabilities) == {"750", "1000", "2500", "5000"}
    assert D("0") <= first.probability_below_start <= D("1")


def test_stress_scenarios_worsen_returns_deterministically() -> None:
    source = (D("0.02"), D("-0.01"))
    scenario = StressScenario(
        "spread-and-slippage",
        extra_cost_per_trade=D("0.005"),
        loser_multiplier=D("1.5"),
    )
    stressed = apply_stress(source, scenario, seed=1)
    assert stressed == (D("0.015"), D("-0.020"))


def test_strategy_health_suspends_deterministically() -> None:
    monitor = StrategyHealthMonitor(HealthThresholds(minimum_trades=3))
    report = monitor.assess(
        (D("-0.02"), D("-0.01"), D("-0.03")),
        maximum_drawdown=D("0.25"),
    )
    assert report.state is StrategyHealth.SUSPENDED
    assert report.expectancy < D("0")


def test_replay_of_the_same_audit_stream_is_reproducible() -> None:
    timestamp = datetime(2024, 1, 1, tzinfo=UTC)
    events = (
        AuditEvent(1, timestamp, "MARKET_BAR_COMPLETED", {"close": "100"}),
        AuditEvent(2, timestamp + timedelta(hours=1), "CANDIDATE_CREATED", {"score": "0.1"}),
    )
    first = tuple(ReplaySession(events).remaining())
    second = tuple(ReplaySession(events).remaining())
    assert first == second
    assert [event.sequence for event in first] == [1, 2]


def test_champion_promotion_requires_complete_manual_evidence() -> None:
    registry = StrategyRegistry()
    created = datetime(2024, 1, 1, tzinfo=UTC)
    version = StrategyVersion("v1", "Quant", {"period": 20}, created, "abc123")
    registry.register(version)
    evidence = PromotionEvidence(True, True, True, True, "administrator", created)
    assert registry.promote("v1", evidence) == version
    assert registry.champion == version
