from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from app.backtesting.costs import CostPreset
from app.backtesting.data_guard import GuardedBarSeries, MarketView
from app.backtesting.fingerprint import SIMULATOR_BEHAVIOR_VERSION, research_fingerprint
from app.backtesting.models import Bar, FillPolicy
from app.core.clock import SimulationClock
from app.instruments import Instrument
from app.instruments.catalog import CORE_UNIVERSE
from app.jobs.backtest_service import _strategy
from app.research.evaluator import (
    CausalWarmupStrategy,
    ResearchProtocolEvaluator,
    ResearchProtocolViolation,
    aggregate_segments,
)
from app.research.models import DataSnapshot, PromotionStatus, json_value
from app.research.protocol import FROZEN_PROTOCOL, RETROSPECTIVE_LABEL
from app.research.provenance import (
    STRATEGY_IMPLEMENTATION_PACKAGES,
    build_strategy_implementation_provenance,
    load_strategy_implementation_provenance,
)
from app.strategies import Strategy, TrendBreakoutStrategy

D = Decimal


def _bar(timestamp: datetime, symbol: str, close: str = "100") -> Bar:
    price = D(close)
    return Bar(
        timestamp,
        price,
        price + D("1"),
        price - D("1"),
        price,
        instrument_id=symbol,
    )


class _ObservingStrategy(Strategy):
    version_id = "observer-v1"

    def __init__(self) -> None:
        self.visible_timestamps: tuple[datetime, ...] = ()

    def evaluate(self, view: MarketView):  # type: ignore[no-untyped-def]
        self.visible_timestamps = tuple(bar.timestamp for bar in view.bars)
        return None


def _test_instruments() -> dict[str, Instrument]:
    return {
        symbol: Instrument.from_definition(CORE_UNIVERSE[symbol])
        for symbol in FROZEN_PROTOCOL.symbols
    }


def _protocol_data() -> tuple[dict[str, tuple[Bar, ...]], DataSnapshot]:
    bars: dict[str, tuple[Bar, ...]] = {}
    for offset, symbol in enumerate(FROZEN_PROTOCOL.symbols):
        timestamp = FROZEN_PROTOCOL.history_start
        values: list[Bar] = []
        while timestamp < FROZEN_PROTOCOL.history_end:
            if timestamp.weekday() < 5:
                values.append(_bar(timestamp, symbol, str(100 + offset)))
            timestamp += timedelta(days=1)
        bars[symbol] = tuple(values)
    checksums = {symbol: f"{index:064x}" for index, symbol in enumerate(bars, 1)}
    ids = {symbol: f"manifest-{index}" for index, symbol in enumerate(bars, 1)}
    snapshot = DataSnapshot.from_bars(
        provider=FROZEN_PROTOCOL.provider,
        interval=FROZEN_PROTOCOL.interval,
        window_start=FROZEN_PROTOCOL.history_start,
        window_end=FROZEN_PROTOCOL.history_end,
        bars_by_instrument=bars,
        manifest_checksums=checksums,
        manifest_ids=ids,
    )
    return bars, snapshot


@pytest.fixture(scope="module")
def evaluated_protocol():  # type: ignore[no-untyped-def]
    bars, snapshot = _protocol_data()
    evaluator = ResearchProtocolEvaluator(
        bars_by_instrument=bars,
        data_snapshot=snapshot,
        instruments=_test_instruments(),
        strategy_factory=_strategy,
    )
    first = evaluator.evaluate()
    portable_snapshot = replace(
        snapshot,
        manifest_ids=tuple(
            (symbol, f"other-database-{index}")
            for index, symbol in enumerate(FROZEN_PROTOCOL.symbols, 1)
        ),
    )
    second = ResearchProtocolEvaluator(
        bars_by_instrument=bars,
        data_snapshot=portable_snapshot,
        instruments=_test_instruments(),
        strategy_factory=_strategy,
    ).evaluate()
    return evaluator, first, second


def test_frozen_boundaries_roster_and_gates_are_predeclared() -> None:
    protocol = FROZEN_PROTOCOL
    assert protocol.protocol_version == "1.2.0"
    assert protocol.label == RETROSPECTIVE_LABEL
    assert len(protocol.symbols) == 9
    assert [fold.fold_id for fold in protocol.folds] == [f"fold-{index}" for index in range(1, 6)]
    assert [fold.test_start.year for fold in protocol.folds] == [2022, 2023, 2024, 2025, 2026]
    assert protocol.folds[-1].test_end == datetime(2026, 8, 19, tzinfo=UTC)
    assert {spec.version_prefix for spec in protocol.strategies} == {
        "quant-baseline-v1",
        "quant-aggressive-v1",
        "regime-ensemble-v1",
    }
    assert protocol.gates.minimum_aggregate_profit_factor == D("1.10")
    assert protocol.gates.minimum_aggregate_trades == 50
    assert protocol.gates.maximum_worst_fold_drawdown == D("0.15")
    assert protocol.conversion_timing_policy_id == "modeled-bar-open-conversion-v1"
    assert (
        protocol.fill_risk_revalidation_policy_id == "fill-risk-revalidation-v1-reservation-capped"
    )
    assert protocol.simulator_behavior_version == SIMULATOR_BEHAVIOR_VERSION
    assert (
        protocol.strategy_implementation_digest == load_strategy_implementation_provenance().digest
    )
    with pytest.raises(ValueError, match="eligibility gates are frozen"):
        replace(
            protocol,
            gates=replace(protocol.gates, minimum_aggregate_trades=51),
        )
    with pytest.raises(ValueError, match="identifiers are frozen"):
        replace(protocol, conversion_timing_policy_id="completion-time-conversion")
    with pytest.raises(ValueError, match="identifiers are frozen"):
        replace(protocol, simulator_behavior_version="historical-simulator-v3-market-realism")
    with pytest.raises(ValueError, match="implementation provenance is frozen"):
        replace(protocol, strategy_implementation_digest="0" * 64)


@pytest.mark.parametrize(
    ("field_name", "changed_value"),
    (
        ("protocol_id", "changed-protocol"),
        ("protocol_version", "1.2.1"),
        ("label", "CHANGED"),
        ("history_start", FROZEN_PROTOCOL.history_start + timedelta(days=1)),
        ("history_end", FROZEN_PROTOCOL.history_end - timedelta(days=1)),
        ("interval", "1h"),
        ("provider", "changed-provider"),
        ("starting_equity", D("501")),
        ("cost_preset", CostPreset.ZERO),
        ("fill_policy", FillPolicy.TARGET_FIRST),
        ("maximum_holding_bars", 3),
        ("execution_delay_bars", 2),
        ("seed", 8501),
        ("risk_taper", True),
        ("warmup_calendar_days", 399),
        ("minimum_warmup_bars_per_market", 59),
        ("minimum_business_day_coverage", D("0.84")),
        ("maximum_boundary_lag_days", 9),
    ),
)
def test_frozen_protocol_rejects_scalar_runtime_mutation(
    field_name: str,
    changed_value: object,
) -> None:
    with pytest.raises(ValueError, match="scalar configuration is frozen"):
        replace(FROZEN_PROTOCOL, **{field_name: changed_value})


def test_evaluator_constructs_the_frozen_execution_policies(
    evaluated_protocol,  # type: ignore[no-untyped-def]
) -> None:
    evaluator, _, _ = evaluated_protocol
    assert (
        evaluator.conversion_timing_policy.policy_id == FROZEN_PROTOCOL.conversion_timing_policy_id
    )
    assert (
        evaluator.fill_revalidation_policy.policy_id
        == FROZEN_PROTOCOL.fill_risk_revalidation_policy_id
    )
    assert FROZEN_PROTOCOL.simulator_behavior_version == SIMULATOR_BEHAVIOR_VERSION
    assert (
        evaluator.strategy_implementation_provenance.digest
        == FROZEN_PROTOCOL.strategy_implementation_digest
    )


def test_strategy_source_provenance_is_complete_portable_and_content_sensitive() -> None:
    current = load_strategy_implementation_provenance()
    covered_packages = {module.logical_path.split("/", maxsplit=2)[1] for module in current.modules}
    assert covered_packages == set(STRATEGY_IMPLEMENTATION_PACKAGES)
    assert all(module.logical_path.endswith(".py") for module in current.modules)
    assert all("__pycache__" not in module.logical_path for module in current.modules)
    assert all(not module.logical_path.startswith("/") for module in current.modules)

    # Logical module names, not mapping order, checkout paths, or platform line
    # endings, form the identity. A real logic change must change it.
    baseline = build_strategy_implementation_provenance(
        {
            "app/strategies/example.py": b"def score():\r\n    return 1\r\n",
            "app/opportunities/scoring.py": b"VALUE = 1\r\n",
        }
    )
    portable = build_strategy_implementation_provenance(
        {
            "app/opportunities/scoring.py": "VALUE = 1\n",
            "app/strategies/example.py": "def score():\n    return 1\n",
        }
    )
    changed = build_strategy_implementation_provenance(
        {
            "app/opportunities/scoring.py": "VALUE = 1\n",
            "app/strategies/example.py": "def score():\n    return 2\n",
        }
    )
    assert baseline.digest == portable.digest
    assert changed.digest != baseline.digest
    assert changed.modules != baseline.modules


def test_source_digest_perturbation_changes_canonical_research_identities() -> None:
    baseline = build_strategy_implementation_provenance(
        {"app/strategies/example.py": "def signal():\n    return True\n"}
    )
    changed = build_strategy_implementation_provenance(
        {"app/strategies/example.py": "def signal():\n    return False\n"}
    )
    for kind in (
        "strategy_protocol_configuration",
        "strategy_research_result",
        "research_protocol_report",
    ):
        stable_payload = {"unchanged_inputs": ("strategy-v1", "data-v1")}
        baseline_identity = research_fingerprint(
            {
                "kind": kind,
                "payload": stable_payload,
                "strategy_implementation_provenance": baseline,
            }
        )
        changed_identity = research_fingerprint(
            {
                "kind": kind,
                "payload": stable_payload,
                "strategy_implementation_provenance": changed,
            }
        )
        assert changed_identity != baseline_identity


def test_evaluator_fails_closed_when_loaded_strategy_source_does_not_match(
    evaluated_protocol,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evaluator, _, _ = evaluated_protocol
    changed = build_strategy_implementation_provenance(
        {"app/strategies/example.py": "def signal():\n    return False\n"}
    )
    monkeypatch.setattr(
        "app.research.evaluator.load_strategy_implementation_provenance",
        lambda: changed,
    )
    with pytest.raises(ResearchProtocolViolation, match="source digest"):
        ResearchProtocolEvaluator(
            bars_by_instrument=evaluator.bars_by_instrument,
            data_snapshot=evaluator.data_snapshot,
            instruments=_test_instruments(),
            strategy_factory=_strategy,
        )


def test_manifest_database_ids_do_not_change_the_data_fingerprint() -> None:
    timestamps = (datetime(2020, 1, 1, tzinfo=UTC), datetime(2020, 1, 2, tzinfo=UTC))
    bars = {"GBPUSD": tuple(_bar(timestamp, "GBPUSD") for timestamp in timestamps)}
    common = {
        "provider": "test",
        "interval": "1d",
        "window_start": datetime(2020, 1, 1, tzinfo=UTC),
        "window_end": datetime(2020, 2, 1, tzinfo=UTC),
        "bars_by_instrument": bars,
        "manifest_checksums": {"GBPUSD": "a" * 64},
    }
    sqlite = DataSnapshot.from_bars(**common, manifest_ids={"GBPUSD": "sqlite-row"})
    postgres = DataSnapshot.from_bars(**common, manifest_ids={"GBPUSD": "postgres-row"})
    revised = DataSnapshot.from_bars(
        **{**common, "manifest_checksums": {"GBPUSD": "b" * 64}},
        manifest_ids={"GBPUSD": "postgres-row"},
    )
    assert sqlite.manifest_ids != postgres.manifest_ids
    assert sqlite.fingerprint == postgres.fingerprint
    assert sqlite.fingerprint != revised.fingerprint
    missing_interval_revision = DataSnapshot.from_bars(
        **common,
        manifest_ids={"GBPUSD": "sqlite-row"},
        manifest_missing_intervals={"GBPUSD": 1},
    )
    assert sqlite.fingerprint != missing_interval_revision.fingerprint
    with pytest.raises(ValueError, match="row counts do not match"):
        DataSnapshot.from_bars(
            **common,
            manifest_declared_row_counts={"GBPUSD": 1},
        )


def test_causal_warmup_is_visible_to_indicators_but_not_the_engine() -> None:
    start = datetime(2024, 1, 3, tzinfo=UTC)
    warmup = (
        _bar(datetime(2024, 1, 1, tzinfo=UTC), "GBPUSD"),
        _bar(datetime(2024, 1, 2, tzinfo=UTC), "GBPUSD"),
    )
    segment = (
        _bar(start, "GBPUSD"),
        _bar(start + timedelta(days=1), "GBPUSD"),
    )
    observer = _ObservingStrategy()
    wrapped = CausalWarmupStrategy(
        observer,
        warmup,
        segment_start=start,
        segment_end=start + timedelta(days=2),
    )
    clock = SimulationClock(start)
    view = MarketView(_test_instruments()["GBPUSD"], GuardedBarSeries(segment, clock))
    assert wrapped.evaluate(view) is None
    assert observer.visible_timestamps == (
        warmup[0].timestamp,
        warmup[1].timestamp,
        segment[0].timestamp,
    )
    assert all(bar.timestamp >= start for bar in view.bars)


def test_incomplete_history_fails_before_any_fold_runs(evaluated_protocol) -> None:  # type: ignore[no-untyped-def]
    evaluator, _, _ = evaluated_protocol
    sparse = dict(evaluator.bars_by_instrument)
    final_test = FROZEN_PROTOCOL.folds[-1]
    final_bars = tuple(
        bar
        for bar in sparse["GBPUSD"]
        if final_test.test_start <= bar.timestamp < final_test.test_end
    )
    retained_final_timestamps = {final_bars[0].timestamp, final_bars[-1].timestamp}
    sparse["GBPUSD"] = tuple(
        bar
        for bar in sparse["GBPUSD"]
        if not final_test.test_start <= bar.timestamp < final_test.test_end
        or bar.timestamp in retained_final_timestamps
    )
    snapshot = DataSnapshot.from_bars(
        provider=FROZEN_PROTOCOL.provider,
        interval=FROZEN_PROTOCOL.interval,
        window_start=FROZEN_PROTOCOL.history_start,
        window_end=FROZEN_PROTOCOL.history_end,
        bars_by_instrument=sparse,
        manifest_checksums={symbol: f"{index:064x}" for index, symbol in enumerate(sparse, 1)},
    )
    with pytest.raises(ResearchProtocolViolation, match="fold-5 test daily coverage"):
        ResearchProtocolEvaluator(
            bars_by_instrument=sparse,
            data_snapshot=snapshot,
            instruments=_test_instruments(),
            strategy_factory=_strategy,
        )


def test_predeclared_parameter_digest_rejects_silent_strategy_drift(
    evaluated_protocol,  # type: ignore[no-untyped-def]
) -> None:
    evaluator, _, _ = evaluated_protocol

    def drifted_factory(name: str, symbol: str) -> Strategy:
        strategy = _strategy(name, symbol)
        if name == "Quant Baseline":
            assert isinstance(strategy, TrendBreakoutStrategy)
            strategy.config = replace(strategy.config, fast_period=11)
        return strategy

    drifted = ResearchProtocolEvaluator(
        bars_by_instrument=evaluator.bars_by_instrument,
        data_snapshot=evaluator.data_snapshot,
        instruments=_test_instruments(),
        strategy_factory=drifted_factory,
    )
    with pytest.raises(ResearchProtocolViolation, match="parameter state changed"):
        drifted.evaluate()


def test_protocol_report_is_deterministic_and_fails_closed_without_stress(
    evaluated_protocol,  # type: ignore[no-untyped-def]
) -> None:
    _, first, second = evaluated_protocol
    assert first.report_fingerprint == second.report_fingerprint
    assert first.data_snapshot.manifest_ids != second.data_snapshot.manifest_ids
    assert first.label == RETROSPECTIVE_LABEL
    assert "not an untouched holdout" in first.disclosure
    assert (
        first.strategy_implementation_provenance.digest
        == FROZEN_PROTOCOL.strategy_implementation_digest
    )
    serialized = json_value(first)
    assert serialized["strategy_implementation_provenance"]["digest"] == (
        FROZEN_PROTOCOL.strategy_implementation_digest
    )
    assert serialized["strategy_implementation_provenance"]["modules"]
    assert all(
        set(module) == {"logical_path", "sha256", "normalized_byte_count"}
        for module in serialized["strategy_implementation_provenance"]["modules"]
    )
    assert len(first.strategy_results) == 3
    for result in first.strategy_results:
        assert (
            result.strategy_implementation_digest == FROZEN_PROTOCOL.strategy_implementation_digest
        )
        assert result.parameter_state_stable is True
        assert set(result.per_market_strategy_fingerprints) == set(FROZEN_PROTOCOL.symbols)
        assert len(result.folds) == 5
        assert all(fold.label == RETROSPECTIVE_LABEL for fold in result.folds)
        assert all(fold.test.reproducibility_checked for fold in result.folds)
        assert all(fold.test.reproducible for fold in result.folds)
        assert len(result.stability_to_test_degradation.annualised_return_deltas) == 5
        assert all(
            set(fold.test.reference_bar_counts) == {"GBPUSD", "EURGBP", "USDJPY"}
            for fold in result.folds
        )
        assert result.verdict.status is PromotionStatus.NOT_ELIGIBLE
        assert result.verdict.promotion_allowed is False
        assert result.stressed_test_aggregate is not None
        assert any(
            reason.startswith("COST_STRESS_1_5X_RETURN:") for reason in result.verdict.unmet_gates
        )


def test_positive_retrospective_gates_still_cannot_authorize_promotion(
    evaluated_protocol,  # type: ignore[no-untyped-def]
) -> None:
    evaluator, report, _ = evaluated_protocol
    result = report.strategy_results[0]
    passing_test = replace(
        result.test_aggregate,
        fold_count=5,
        after_cost_return=D("0.10"),
        median_fold_return=D("0.02"),
        positive_folds=3,
        aggregate_trades=50,
        folds_with_at_least_five_trades=4,
        aggregate_profit_factor=D("1.10"),
        profit_factor_is_infinite=False,
        worst_fold_maximum_drawdown=D("0.15"),
        any_ruin=False,
    )
    passing_stability = replace(result.stability_aggregate, after_cost_return=D("0.01"))
    passing_stress = replace(result.test_aggregate, after_cost_return=D("0.01"))
    verdict = evaluator._verdict(
        result.folds,
        passing_test,
        passing_stability,
        passing_stress,
    )
    assert verdict.research_gates_passed is True
    assert verdict.status is PromotionStatus.RESEARCH_GATES_PASSED_PROMOTION_BLOCKED
    assert verdict.promotion_allowed is False
    assert verdict.unmet_gates == ()


def test_aggregate_reports_cross_fold_instrument_and_regime_consistency(
    evaluated_protocol,  # type: ignore[no-untyped-def]
) -> None:
    _, report, _ = evaluated_protocol
    original = report.strategy_results[0].folds[0].test
    first = replace(
        original,
        metrics=replace(
            original.metrics,
            total_return=D("0.02"),
            final_equity=D("510"),
            performance_by_instrument={"GBPUSD": D("10")},
            performance_by_regime={"TRENDING_UP": D("10")},
        ),
    )
    second = replace(
        original,
        metrics=replace(
            original.metrics,
            total_return=D("-0.01"),
            final_equity=D("495"),
            performance_by_instrument={"GBPUSD": D("-5"), "SP500": D("2")},
            performance_by_regime={"TRENDING_UP": D("-5"), "RANGING": D("2")},
        ),
    )
    aggregate = aggregate_segments((first, second))
    by_instrument = {item.key: item for item in aggregate.performance_by_instrument}
    by_regime = {item.key: item for item in aggregate.performance_by_regime}
    assert by_instrument["GBPUSD"].aggregate_net_pnl == D("5.00")
    assert by_instrument["GBPUSD"].profitable_folds == 1
    assert by_instrument["SP500"].folds_present == 1
    assert by_regime["RANGING"].folds_present == 1
