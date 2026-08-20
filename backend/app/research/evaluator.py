"""Execution and fail-closed gating for the frozen research protocol."""

from __future__ import annotations

import itertools
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from app.backtesting.conversion import ConversionTimingPolicy, QuoteToGbpConversionPolicy
from app.backtesting.data_guard import GuardedBarSeries, MarketView
from app.backtesting.fill_revalidation import FillRiskRevalidationPolicy
from app.backtesting.fingerprint import SIMULATOR_BEHAVIOR_VERSION, research_fingerprint
from app.backtesting.models import Bar
from app.backtesting.portfolio_engine import PortfolioBacktestEngine, PortfolioBacktestResult
from app.backtesting.research_costs import ResearchCostAssumption, ResearchCostSchedule
from app.backtesting.sessions import MarketSessionPolicy
from app.core.clock import SimulationClock
from app.core.decimal import ZERO, money
from app.instruments import Instrument
from app.opportunities import OpportunityCandidate
from app.risk import RiskLimits, limits_for_profile
from app.strategies import Strategy

from .models import (
    AggregateMetrics,
    BreakdownConsistency,
    CostStressScenario,
    DataSnapshot,
    FoldResult,
    PromotionStatus,
    PromotionVerdict,
    ResearchProtocolReport,
    SegmentKind,
    SegmentResult,
    StabilityDegradationSummary,
    StrategyResearchResult,
)
from .protocol import (
    FROZEN_PROTOCOL,
    RETROSPECTIVE_LABEL,
    ResearchProtocol,
    StrategySpecification,
)
from .provenance import load_strategy_implementation_provenance

StrategyFactory = Callable[[str, str], Strategy]


class ResearchProtocolViolation(RuntimeError):
    """A fail-closed protocol, data, or causality violation."""


class CausalWarmupStrategy(Strategy):
    """Expose pre-segment bars to indicators without stepping the trade engine.

    The portfolio engine receives only evaluation-window bars and therefore
    creates its ledger, risk engine, circuit breakers, and equity curve at the
    segment boundary.  This adapter builds a point-in-time view containing the
    immutable warm-up prefix plus only the evaluation bars already visible to
    the engine clock.  Warm-up observations can inform indicators, but cannot
    produce an order or mutate trading state.
    """

    def __init__(
        self,
        wrapped: Strategy,
        warmup_bars: Sequence[Bar],
        *,
        segment_start: datetime,
        segment_end: datetime,
    ) -> None:
        bars = tuple(sorted(warmup_bars, key=lambda bar: bar.timestamp))
        if any(bar.timestamp >= segment_start for bar in bars):
            raise ValueError("warm-up bars must be strictly before the evaluation segment")
        self.wrapped = wrapped
        self.warmup_bars = bars
        self.segment_start = segment_start
        self.segment_end = segment_end
        self.version_id = wrapped.version_id

    def evaluate(self, view: MarketView) -> OpportunityCandidate | None:
        if not self.segment_start <= view.now < self.segment_end:
            raise ResearchProtocolViolation("strategy evaluated outside its declared segment")
        visible_segment = view.bars.visible()
        if any(bar.timestamp < self.segment_start for bar in visible_segment):
            raise ResearchProtocolViolation("the execution engine received a warm-up bar")
        virtual_clock = SimulationClock(view.now)
        virtual_bars = GuardedBarSeries((*self.warmup_bars, *visible_segment), virtual_clock)
        candidate = self.wrapped.evaluate(MarketView(view.instrument, virtual_bars))
        if (
            candidate is not None
            and not self.segment_start <= candidate.timestamp < self.segment_end
        ):
            raise ResearchProtocolViolation("warm-up data produced an out-of-segment candidate")
        return candidate


@dataclass(frozen=True, slots=True)
class _ExecutedSegment:
    result: PortfolioBacktestResult
    warmup_start: datetime
    warmup_counts: dict[str, int]
    evaluation_counts: dict[str, int]
    reference_counts: dict[str, int]
    outcome_fingerprint: str
    total_execution_cost: Decimal


class ResearchProtocolEvaluator:
    """Evaluate all predeclared strategies without tuning or winner selection."""

    def __init__(
        self,
        *,
        bars_by_instrument: Mapping[str, Sequence[Bar]],
        data_snapshot: DataSnapshot,
        instruments: Mapping[str, Instrument],
        strategy_factory: StrategyFactory,
        protocol: ResearchProtocol = FROZEN_PROTOCOL,
    ) -> None:
        if protocol != FROZEN_PROTOCOL:
            raise ValueError("only the frozen, fingerprinted protocol may be evaluated")
        self.protocol = protocol
        self.bars_by_instrument = {
            symbol: tuple(sorted(bars, key=lambda bar: bar.timestamp))
            for symbol, bars in bars_by_instrument.items()
        }
        self.data_snapshot = data_snapshot
        self.instruments = dict(instruments)
        self.strategy_factory = strategy_factory
        self.cost_schedule = ResearchCostSchedule()
        self.base_cost_assumptions = self.cost_schedule.assumptions_for(
            list(protocol.symbols), protocol.cost_preset
        )
        stress_multiplier = protocol.gates.required_cost_stress_multiplier
        self.cost_stress_scenario = CostStressScenario(
            name=protocol.cost_stress_scenario_id,
            multiplier=stress_multiplier,
            cost_assumptions={
                symbol: self.cost_schedule.scaled_assumption_for(
                    symbol,
                    stress_multiplier,
                    base_preset=protocol.cost_preset,
                    scenario_id=protocol.cost_stress_scenario_id,
                )
                for symbol in protocol.symbols
            },
        )
        self.conversion_policy = QuoteToGbpConversionPolicy.causal()
        self.conversion_timing_policy = ConversionTimingPolicy()
        self.fill_revalidation_policy = FillRiskRevalidationPolicy()
        self.session_policy = MarketSessionPolicy()
        self.strategy_implementation_provenance = load_strategy_implementation_provenance()
        self._validate_inputs()

    def evaluate(self) -> ResearchProtocolReport:
        results = tuple(
            self._evaluate_strategy(specification) for specification in self.protocol.strategies
        )
        report_payload = {
            "protocol_id": self.protocol.protocol_id,
            "protocol_version": self.protocol.protocol_version,
            "label": self.protocol.label,
            "disclosure": self._disclosure,
            "protocol_fingerprint": self.protocol.fingerprint,
            "source_fingerprint": self.data_snapshot.fingerprint,
            "data_fingerprint": self.data_snapshot.fingerprint,
            "strategy_implementation_provenance": (self.strategy_implementation_provenance),
            "data_snapshot": self.data_snapshot,
            "strategy_results": results,
        }
        canonical_report_payload = {
            key: value for key, value in report_payload.items() if key != "data_snapshot"
        }
        return ResearchProtocolReport(
            protocol_id=self.protocol.protocol_id,
            protocol_version=self.protocol.protocol_version,
            label=self.protocol.label,
            disclosure=self._disclosure,
            protocol_fingerprint=self.protocol.fingerprint,
            source_fingerprint=self.data_snapshot.fingerprint,
            data_fingerprint=self.data_snapshot.fingerprint,
            strategy_implementation_provenance=(self.strategy_implementation_provenance),
            data_snapshot=self.data_snapshot,
            strategy_results=results,
            report_fingerprint=research_fingerprint(
                {"kind": "research_protocol_report", "report": canonical_report_payload}
            ),
        )

    @property
    def _disclosure(self) -> str:
        return (
            "All splits in the 2018-01-01 to 2026-08-19-exclusive window are "
            f"{RETROSPECTIVE_LABEL} (retrospective pseudo-out-of-sample): the complete "
            "history was inspected before this protocol was frozen. These results are not "
            "an untouched holdout and cannot authorize promotion to demo or live trading."
        )

    def _validate_inputs(self) -> None:
        expected = set(self.protocol.symbols)
        if set(self.bars_by_instrument) != expected:
            raise ValueError("bar data must cover exactly the frozen nine-market universe")
        if set(self.instruments) != expected:
            raise ValueError("instrument economics must cover exactly the frozen universe")
        if any(self.instruments[symbol].id != symbol for symbol in self.protocol.symbols):
            raise ValueError("instrument identifiers must match their data symbols")
        for symbol, bars in self.bars_by_instrument.items():
            if len(bars) < 2:
                raise ValueError(f"{symbol} requires at least two completed daily bars")
            if any(left.timestamp >= right.timestamp for left, right in itertools.pairwise(bars)):
                raise ValueError(f"{symbol} timestamps must be strictly increasing")
            if any(bar.instrument_id and bar.instrument_id != symbol for bar in bars):
                raise ValueError(f"{symbol} contains a mismatched instrument identifier")
            self._validate_history_coverage(symbol, bars)
            self._validate_segment_coverage(symbol, bars)
        snapshot_checksums = dict(self.data_snapshot.manifest_checksums)
        snapshot_ids = dict(self.data_snapshot.manifest_ids)
        rebuilt = DataSnapshot.from_bars(
            provider=self.data_snapshot.provider,
            interval=self.data_snapshot.interval,
            window_start=self.data_snapshot.window_start,
            window_end=self.data_snapshot.window_end,
            bars_by_instrument=self.bars_by_instrument,
            manifest_checksums=snapshot_checksums,
            manifest_ids=snapshot_ids or None,
            manifest_declared_row_counts=dict(self.data_snapshot.manifest_declared_row_counts),
            manifest_missing_intervals=dict(self.data_snapshot.manifest_missing_intervals),
            manifest_start_at=dict(self.data_snapshot.manifest_start_at),
            manifest_end_at=dict(self.data_snapshot.manifest_end_at),
        )
        if rebuilt.fingerprint != self.data_snapshot.fingerprint:
            raise ResearchProtocolViolation("data snapshot does not match the supplied bars")
        if self.data_snapshot.provider != self.protocol.provider:
            raise ValueError("data provider does not match the frozen protocol")
        if self.data_snapshot.interval != self.protocol.interval:
            raise ValueError("data interval does not match the frozen protocol")
        if self.data_snapshot.window_start != self.protocol.history_start:
            raise ValueError("data snapshot starts outside the frozen research window")
        if self.data_snapshot.window_end != self.protocol.history_end:
            raise ValueError("data snapshot ends outside the frozen research window")
        if set(self.data_snapshot.symbols) != expected:
            raise ValueError("data snapshot symbols do not match the frozen universe")
        if self.cost_schedule.schedule_id != self.protocol.research_cost_schedule_id:
            raise ValueError("research cost schedule does not match the frozen protocol")
        if self.conversion_policy.policy_id != self.protocol.conversion_policy_id:
            raise ValueError("conversion policy does not match the frozen protocol")
        if self.conversion_timing_policy.policy_id != self.protocol.conversion_timing_policy_id:
            raise ValueError("conversion timing policy does not match the frozen protocol")
        if (
            self.fill_revalidation_policy.policy_id
            != self.protocol.fill_risk_revalidation_policy_id
        ):
            raise ValueError("fill risk revalidation policy does not match the frozen protocol")
        if self.session_policy.policy_id != self.protocol.session_policy_id:
            raise ValueError("session policy does not match the frozen protocol")
        if self.protocol.simulator_behavior_version != SIMULATOR_BEHAVIOR_VERSION:
            raise ValueError("simulator behavior does not match the frozen protocol")
        if (
            self.strategy_implementation_provenance.schema_version
            != self.protocol.strategy_implementation_provenance_schema
        ):
            raise ResearchProtocolViolation(
                "strategy implementation provenance schema does not match the frozen protocol"
            )
        if (
            self.strategy_implementation_provenance.digest
            != self.protocol.strategy_implementation_digest
        ):
            raise ResearchProtocolViolation(
                "strategy implementation source digest does not match the frozen protocol"
            )
        if set(self.base_cost_assumptions) != expected:
            raise ValueError("base cost assumptions must cover every frozen market")
        if set(self.cost_stress_scenario.cost_assumptions) != expected:
            raise ValueError("the cost stress scenario must cover every frozen market")
        if (
            self.cost_stress_scenario.multiplier
            != self.protocol.gates.required_cost_stress_multiplier
        ):
            raise ValueError("the cost stress multiplier does not match the frozen gate")
        self._validate_scaled_costs()

    def _validate_history_coverage(self, symbol: str, bars: Sequence[Bar]) -> None:
        coverage = self._coverage_ratio(
            bars, self.protocol.history_start, self.protocol.history_end
        )
        if coverage < self.protocol.minimum_business_day_coverage:
            raise ResearchProtocolViolation(
                f"{symbol} daily coverage {coverage} is below the frozen minimum "
                f"{self.protocol.minimum_business_day_coverage}"
            )
        boundary_lag = timedelta(days=self.protocol.maximum_boundary_lag_days)
        if bars[0].timestamp > self.protocol.history_start + boundary_lag:
            raise ResearchProtocolViolation(f"{symbol} starts too late for the frozen history")
        if bars[-1].timestamp < self.protocol.history_end - boundary_lag:
            raise ResearchProtocolViolation(f"{symbol} ends too early for the frozen history")

    def _validate_segment_coverage(self, symbol: str, bars: Sequence[Bar]) -> None:
        intervals: list[tuple[str, datetime, datetime]] = []
        for fold in self.protocol.folds:
            intervals.extend(
                (
                    (
                        f"{fold.fold_id} stability warm-up",
                        self.protocol.warmup_start(fold.stability_start),
                        fold.stability_start,
                    ),
                    (
                        f"{fold.fold_id} stability",
                        fold.stability_start,
                        fold.stability_end,
                    ),
                    (
                        f"{fold.fold_id} test warm-up",
                        self.protocol.warmup_start(fold.test_start),
                        fold.test_start,
                    ),
                    (f"{fold.fold_id} test", fold.test_start, fold.test_end),
                )
            )
        for label, start, end in intervals:
            coverage = self._coverage_ratio(bars, start, end)
            if coverage < self.protocol.minimum_business_day_coverage:
                raise ResearchProtocolViolation(
                    f"{symbol} {label} daily coverage {coverage} is below the frozen "
                    f"minimum {self.protocol.minimum_business_day_coverage}"
                )

    @staticmethod
    def _coverage_ratio(bars: Sequence[Bar], start: datetime, end: datetime) -> Decimal:
        window_days = (end.date() - start.date()).days
        expected_business_days = sum(
            (start + timedelta(days=offset)).weekday() < 5 for offset in range(window_days)
        )
        observed_dates = {bar.timestamp.date() for bar in bars if start <= bar.timestamp < end}
        if expected_business_days == 0:
            return ZERO
        return Decimal(len(observed_dates)) / Decimal(expected_business_days)

    def _validate_scaled_costs(self) -> None:
        factor = self.protocol.gates.required_cost_stress_multiplier
        for symbol in self.protocol.symbols:
            base = self.base_cost_assumptions[symbol].model
            stressed = self.cost_stress_scenario.cost_assumptions[symbol].model
            for field in (
                "spread_bps",
                "slippage_bps_per_side",
                "commission_bps_per_side",
                "financing_bps_per_day",
                "guaranteed_stop_premium_bps",
                "currency_conversion_bps",
            ):
                if getattr(stressed, field) != getattr(base, field) * factor:
                    raise ResearchProtocolViolation(
                        f"{symbol} {field} is not exactly {factor}x the frozen base cost"
                    )

    def _evaluate_strategy(self, specification: StrategySpecification) -> StrategyResearchResult:
        expected_states = self._strategy_states(specification)
        per_market_strategy_fingerprints = {
            symbol: research_fingerprint(
                {
                    "kind": "implementation_bound_strategy_state",
                    "implementation_digest": (self.strategy_implementation_provenance.digest),
                    "strategy": strategy,
                }
            )
            for symbol, strategy in expected_states.items()
        }
        strategy_fingerprint = research_fingerprint(
            {
                "kind": "immutable_strategy",
                "implementation_provenance": self.strategy_implementation_provenance,
                "specification": specification,
                "per_market_state": expected_states,
            }
        )
        risk_limits = limits_for_profile(specification.risk_profile)
        economics_payload = {
            "instruments": self.instruments,
            "cost_schedule": self.cost_schedule,
            "base_cost_assumptions": self.base_cost_assumptions,
            "cost_stress_scenario": self.cost_stress_scenario,
            "conversion_policy": self.conversion_policy,
            "conversion_timing_policy": self.conversion_timing_policy,
            "fill_revalidation_policy": self.fill_revalidation_policy,
            "session_policy": self.session_policy,
            "simulator_behavior_version": SIMULATOR_BEHAVIOR_VERSION,
        }
        economics_fingerprint = research_fingerprint(
            {"kind": "instrument_and_cost_economics", "economics": economics_payload}
        )
        config_fingerprint = research_fingerprint(
            {
                "kind": "strategy_protocol_configuration",
                "protocol": self.protocol,
                "backtest_config": self.protocol.backtest_config,
                "risk_limits": risk_limits,
                "risk_taper": self.protocol.risk_taper,
                "strategy_specification": specification,
                "strategy_implementation_provenance": (self.strategy_implementation_provenance),
                "execution_economics": economics_payload,
            }
        )

        folds: list[FoldResult] = []
        for boundary in self.protocol.folds:
            stability = self._run_segment(
                specification,
                expected_states,
                boundary.fold_id,
                SegmentKind.STABILITY,
                boundary.stability_start,
                boundary.stability_end,
                risk_limits=risk_limits,
                cost_assumptions=self.base_cost_assumptions,
                cost_scenario=self.protocol.research_cost_schedule_id,
                verify_reproducibility=False,
                strategy_fingerprint=strategy_fingerprint,
                config_fingerprint=config_fingerprint,
                economics_fingerprint=economics_fingerprint,
            )
            test = self._run_segment(
                specification,
                expected_states,
                boundary.fold_id,
                SegmentKind.TEST,
                boundary.test_start,
                boundary.test_end,
                risk_limits=risk_limits,
                cost_assumptions=self.base_cost_assumptions,
                cost_scenario=self.protocol.research_cost_schedule_id,
                verify_reproducibility=True,
                strategy_fingerprint=strategy_fingerprint,
                config_fingerprint=config_fingerprint,
                economics_fingerprint=economics_fingerprint,
            )
            stressed_test = self._run_segment(
                specification,
                expected_states,
                boundary.fold_id,
                SegmentKind.COST_STRESS_TEST,
                boundary.test_start,
                boundary.test_end,
                risk_limits=risk_limits,
                cost_assumptions=self.cost_stress_scenario.cost_assumptions,
                cost_scenario=self.cost_stress_scenario.name,
                verify_reproducibility=False,
                strategy_fingerprint=strategy_fingerprint,
                config_fingerprint=config_fingerprint,
                economics_fingerprint=economics_fingerprint,
            )
            fold_payload = {
                "boundary": boundary,
                "stability_segment_fingerprint": stability.segment_fingerprint,
                "test_segment_fingerprint": test.segment_fingerprint,
                "stressed_test_segment_fingerprint": stressed_test.segment_fingerprint,
                "test_return_delta_vs_stability": (
                    test.metrics.total_return - stability.metrics.total_return
                ),
                "test_annualised_return_delta_vs_stability": _optional_delta(
                    stability.metrics.annualised_return,
                    test.metrics.annualised_return,
                ),
                "test_profit_factor_delta_vs_stability": _profit_factor_delta(
                    stability.metrics.profit_factor, test.metrics.profit_factor
                ),
            }
            folds.append(
                FoldResult(
                    fold_id=boundary.fold_id,
                    label=RETROSPECTIVE_LABEL,
                    train_start=boundary.train_start,
                    train_end=boundary.train_end,
                    stability=stability,
                    test=test,
                    stressed_test=stressed_test,
                    test_return_delta_vs_stability=(
                        test.metrics.total_return - stability.metrics.total_return
                    ),
                    test_annualised_return_delta_vs_stability=_optional_delta(
                        stability.metrics.annualised_return,
                        test.metrics.annualised_return,
                    ),
                    test_profit_factor_delta_vs_stability=_profit_factor_delta(
                        stability.metrics.profit_factor, test.metrics.profit_factor
                    ),
                    fold_fingerprint=research_fingerprint(
                        {"kind": "anchored_walk_forward_fold", "fold": fold_payload}
                    ),
                )
            )

        test_aggregate = aggregate_segments(tuple(fold.test for fold in folds))
        stability_aggregate = aggregate_segments(tuple(fold.stability for fold in folds))
        stressed_aggregate = aggregate_segments(tuple(fold.stressed_test for fold in folds))
        degradation = degradation_summary(tuple(folds))
        verdict = self._verdict(
            tuple(folds), test_aggregate, stability_aggregate, stressed_aggregate
        )
        result_payload = {
            "strategy_key": specification.key,
            "strategy_name": specification.display_name,
            "strategy_implementation_digest": (self.strategy_implementation_provenance.digest),
            "strategy_fingerprint": strategy_fingerprint,
            "per_market_strategy_fingerprints": per_market_strategy_fingerprints,
            "parameter_state_stable": True,
            "config_fingerprint": config_fingerprint,
            "economics_fingerprint": economics_fingerprint,
            "folds": tuple(folds),
            "test_aggregate": test_aggregate,
            "stability_aggregate": stability_aggregate,
            "stressed_test_aggregate": stressed_aggregate,
            "stability_to_test_degradation": degradation,
            "verdict": verdict,
        }
        return StrategyResearchResult(
            strategy_key=specification.key,
            strategy_name=specification.display_name,
            strategy_implementation_digest=(self.strategy_implementation_provenance.digest),
            strategy_fingerprint=strategy_fingerprint,
            per_market_strategy_fingerprints=per_market_strategy_fingerprints,
            parameter_state_stable=True,
            config_fingerprint=config_fingerprint,
            economics_fingerprint=economics_fingerprint,
            folds=tuple(folds),
            test_aggregate=test_aggregate,
            stability_aggregate=stability_aggregate,
            stressed_test_aggregate=stressed_aggregate,
            stability_to_test_degradation=degradation,
            verdict=verdict,
            result_fingerprint=research_fingerprint(
                {"kind": "strategy_research_result", "result": result_payload}
            ),
        )

    def _strategy_states(self, specification: StrategySpecification) -> dict[str, object]:
        states: dict[str, object] = {}
        for symbol in self.protocol.symbols:
            strategy = self.strategy_factory(specification.display_name, symbol)
            expected_version = f"{specification.version_prefix}:{symbol}"
            if strategy.version_id != expected_version:
                raise ResearchProtocolViolation(
                    f"{specification.display_name} on {symbol} returned {strategy.version_id!r}; "
                    f"the frozen version is {expected_version!r}"
                )
            parameter_fingerprint = self._strategy_parameter_fingerprint(strategy)
            if parameter_fingerprint != specification.parameter_fingerprint:
                raise ResearchProtocolViolation(
                    f"{specification.display_name} parameter state changed: "
                    f"{parameter_fingerprint} != frozen "
                    f"{specification.parameter_fingerprint}"
                )
            states[symbol] = strategy
        return states

    @staticmethod
    def _strategy_parameter_fingerprint(strategy: Strategy) -> str:
        parameter_state = {
            key: value for key, value in vars(strategy).items() if key != "version_id"
        }
        return research_fingerprint(
            {
                "kind": "immutable_strategy_parameters",
                "parameters": {
                    "strategy_type": (f"{type(strategy).__module__}.{type(strategy).__qualname__}"),
                    "parameter_state": parameter_state,
                },
            }
        )

    def _run_segment(
        self,
        specification: StrategySpecification,
        expected_states: Mapping[str, object],
        fold_id: str,
        kind: SegmentKind,
        start: datetime,
        end: datetime,
        *,
        risk_limits: RiskLimits,
        cost_assumptions: Mapping[str, ResearchCostAssumption],
        cost_scenario: str,
        verify_reproducibility: bool,
        strategy_fingerprint: str,
        config_fingerprint: str,
        economics_fingerprint: str,
    ) -> SegmentResult:
        first = self._execute_segment(
            specification,
            expected_states,
            start,
            end,
            risk_limits=risk_limits,
            cost_assumptions=cost_assumptions,
        )
        repeated_fingerprint = None
        reproducible = False
        if verify_reproducibility:
            repeated = self._execute_segment(
                specification,
                expected_states,
                start,
                end,
                risk_limits=risk_limits,
                cost_assumptions=cost_assumptions,
            )
            repeated_fingerprint = repeated.outcome_fingerprint
            reproducible = first.outcome_fingerprint == repeated.outcome_fingerprint
        segment_payload = {
            "fold_id": fold_id,
            "label": RETROSPECTIVE_LABEL,
            "kind": kind,
            "start": start,
            "end": end,
            "warmup_start": first.warmup_start,
            "warmup_counts": first.warmup_counts,
            "evaluation_counts": first.evaluation_counts,
            "reference_counts": first.reference_counts,
            "strategy_implementation_digest": (self.strategy_implementation_provenance.digest),
            "strategy_fingerprint": strategy_fingerprint,
            "config_fingerprint": config_fingerprint,
            "data_fingerprint": self.data_snapshot.fingerprint,
            "source_fingerprint": self.data_snapshot.fingerprint,
            "economics_fingerprint": economics_fingerprint,
            "cost_scenario": cost_scenario,
            "engine_run_fingerprint": first.result.run_fingerprint,
            "outcome_fingerprint": first.outcome_fingerprint,
            "repeated_outcome_fingerprint": repeated_fingerprint,
            "reproducibility_checked": verify_reproducibility,
            "reproducible": reproducible,
        }
        return SegmentResult(
            fold_id=fold_id,
            label=RETROSPECTIVE_LABEL,
            kind=kind,
            start=start,
            end=end,
            warmup_start=first.warmup_start,
            warmup_bar_counts=first.warmup_counts,
            evaluation_bar_counts=first.evaluation_counts,
            reference_bar_counts=first.reference_counts,
            cost_preset=self.protocol.cost_preset,
            cost_scenario=cost_scenario,
            metrics=first.result.metrics,
            total_execution_cost=first.total_execution_cost,
            engine_run_fingerprint=first.result.run_fingerprint,
            outcome_fingerprint=first.outcome_fingerprint,
            repeated_outcome_fingerprint=repeated_fingerprint,
            reproducibility_checked=verify_reproducibility,
            reproducible=reproducible,
            causal_guard_passed=True,
            strategy_versions=dict(sorted(first.result.strategy_versions.items())),
            segment_fingerprint=research_fingerprint(
                {"kind": "research_segment", "segment": segment_payload}
            ),
        )

    def _execute_segment(
        self,
        specification: StrategySpecification,
        expected_states: Mapping[str, object],
        start: datetime,
        end: datetime,
        *,
        risk_limits: RiskLimits,
        cost_assumptions: Mapping[str, ResearchCostAssumption],
    ) -> _ExecutedSegment:
        warmup_start = self.protocol.warmup_start(start)
        warmup: dict[str, tuple[Bar, ...]] = {}
        evaluation: dict[str, tuple[Bar, ...]] = {}
        strategies: dict[str, Strategy] = {}
        underlying_strategies: dict[str, Strategy] = {}
        for symbol in self.protocol.symbols:
            source = self.bars_by_instrument[symbol]
            warmup[symbol] = tuple(bar for bar in source if warmup_start <= bar.timestamp < start)
            evaluation[symbol] = tuple(bar for bar in source if start <= bar.timestamp < end)
            if len(warmup[symbol]) < self.protocol.minimum_warmup_bars_per_market:
                raise ResearchProtocolViolation(
                    f"{symbol} has {len(warmup[symbol])} warm-up bars before {start.isoformat()}; "
                    f"{self.protocol.minimum_warmup_bars_per_market} are required"
                )
            if len(evaluation[symbol]) < 2:
                raise ResearchProtocolViolation(
                    f"{symbol} has insufficient evaluation bars in {start.isoformat()} / "
                    f"{end.isoformat()}"
                )
            strategy = self.strategy_factory(specification.display_name, symbol)
            if research_fingerprint(strategy) != research_fingerprint(expected_states[symbol]):
                raise ResearchProtocolViolation(
                    f"{specification.display_name} state drifted for {symbol}"
                )
            strategies[symbol] = CausalWarmupStrategy(
                strategy,
                warmup[symbol],
                segment_start=start,
                segment_end=end,
            )
            underlying_strategies[symbol] = strategy

        # Constructing a new engine here is intentional: ledger, risk state,
        # breakers, broker orders, and strategy objects never cross segments.
        engine = PortfolioBacktestEngine(
            self.instruments,
            strategies,
            risk_limits=risk_limits,
            cost_assumptions=cost_assumptions,
            conversion_policy=self.conversion_policy,
            conversion_timing_policy=self.conversion_timing_policy,
            fill_revalidation_policy=self.fill_revalidation_policy,
            session_policy=self.session_policy,
            risk_taper=self.protocol.risk_taper,
        )
        conversion_ids = self.conversion_policy.required_instruments(
            [self.instruments[symbol].quote_currency for symbol in self.protocol.symbols]
        )
        references = {symbol: warmup[symbol] for symbol in conversion_ids}
        # Conversion pairs are also traded in this portfolio. The engine merges
        # their strictly pre-segment reference prefix with segment bars for the
        # causal resolver, but reference bars never enter strategy/order events.
        result = engine.run(
            evaluation,
            self.protocol.backtest_config,
            reference_bars_by_instrument=references,
        )
        for symbol, strategy in underlying_strategies.items():
            if research_fingerprint(strategy) != research_fingerprint(expected_states[symbol]):
                raise ResearchProtocolViolation(
                    f"{specification.display_name} mutated parameter state during {symbol} run"
                )
        self._assert_causal_segment(result, start, end)
        outcome_fingerprint = research_fingerprint(
            {
                "kind": "material_backtest_outcome",
                "strategy_implementation_digest": (self.strategy_implementation_provenance.digest),
                "engine_run_fingerprint": result.run_fingerprint,
                "trades": result.trades,
                "equity_curve": result.equity_curve,
                "audit_trail": result.audit_trail,
                "metrics": result.metrics,
                "rejected_candidates": result.rejected_candidates,
                "broker_orders_submitted": result.broker_orders_submitted,
                "orders_by_instrument": result.orders_by_instrument,
            }
        )
        total_cost = money(
            sum((trade.total_cost for trade in result.trades), ZERO)
            + result.metrics.operational_costs
        )
        return _ExecutedSegment(
            result=result,
            warmup_start=warmup_start,
            warmup_counts={symbol: len(bars) for symbol, bars in warmup.items()},
            evaluation_counts={symbol: len(bars) for symbol, bars in evaluation.items()},
            reference_counts={symbol: len(bars) for symbol, bars in references.items()},
            outcome_fingerprint=outcome_fingerprint,
            total_execution_cost=total_cost,
        )

    @staticmethod
    def _assert_causal_segment(
        result: PortfolioBacktestResult, start: datetime, end: datetime
    ) -> None:
        if any(not start <= event.timestamp < end for event in result.audit_trail):
            raise ResearchProtocolViolation("audit event escaped the evaluation segment")
        if any(not start <= point.timestamp < end for point in result.equity_curve):
            raise ResearchProtocolViolation("equity state exists outside the evaluation segment")
        if any(
            trade.entry_timestamp < start
            or trade.exit_timestamp < start
            or trade.entry_timestamp >= end
            or trade.exit_timestamp >= end
            for trade in result.trades
        ):
            raise ResearchProtocolViolation("a trade crossed the evaluation segment boundary")
        if any(event.event_type == "STRATEGY_EXCEPTION" for event in result.audit_trail):
            raise ResearchProtocolViolation("strategy exception tripped a fail-closed breaker")

    def _verdict(
        self,
        folds: tuple[FoldResult, ...],
        test: AggregateMetrics,
        stability: AggregateMetrics,
        stressed: AggregateMetrics | None,
    ) -> PromotionVerdict:
        gates = self.protocol.gates
        failures: list[str] = []
        if test.fold_count != gates.required_fold_count:
            failures.append(
                f"FOLD_COUNT: {test.fold_count} != required {gates.required_fold_count}"
            )
        if gates.require_all_folds_reproducible and not all(
            fold.test.reproducibility_checked and fold.test.reproducible for fold in folds
        ):
            failures.append("REPRODUCIBILITY: not all five test folds reproduced exactly")
        if test.after_cost_return <= gates.minimum_aggregate_after_cost_return_exclusive:
            failures.append(
                "AGGREGATE_AFTER_COST_RETURN: "
                f"{test.after_cost_return} must be > "
                f"{gates.minimum_aggregate_after_cost_return_exclusive}"
            )
        profit_factor_passed = test.profit_factor_is_infinite or (
            test.aggregate_profit_factor is not None
            and test.aggregate_profit_factor >= gates.minimum_aggregate_profit_factor
        )
        if not profit_factor_passed:
            failures.append(
                "AGGREGATE_PROFIT_FACTOR: "
                f"{test.aggregate_profit_factor} must be >= "
                f"{gates.minimum_aggregate_profit_factor}"
            )
        if test.median_fold_return <= gates.minimum_median_fold_return_exclusive:
            failures.append(
                "MEDIAN_FOLD_RETURN: "
                f"{test.median_fold_return} must be > "
                f"{gates.minimum_median_fold_return_exclusive}"
            )
        if test.positive_folds < gates.minimum_positive_folds:
            failures.append(
                f"POSITIVE_FOLDS: {test.positive_folds} < {gates.minimum_positive_folds}"
            )
        if test.aggregate_trades < gates.minimum_aggregate_trades:
            failures.append(
                f"AGGREGATE_TRADES: {test.aggregate_trades} < {gates.minimum_aggregate_trades}"
            )
        if test.folds_with_at_least_five_trades < gates.minimum_folds_with_enough_trades:
            failures.append(
                "FOLDS_WITH_MINIMUM_TRADES: "
                f"{test.folds_with_at_least_five_trades} < "
                f"{gates.minimum_folds_with_enough_trades}; per-fold minimum is "
                f"{gates.minimum_trades_per_counted_fold}"
            )
        if test.worst_fold_maximum_drawdown > gates.maximum_worst_fold_drawdown:
            failures.append(
                "WORST_FOLD_DRAWDOWN: "
                f"{test.worst_fold_maximum_drawdown} > "
                f"{gates.maximum_worst_fold_drawdown}"
            )
        if gates.require_no_ruin and test.any_ruin:
            failures.append("RUIN: at least one test fold reached ruin")
        if stability.after_cost_return <= gates.minimum_stability_after_cost_return_exclusive:
            failures.append(
                "STABILITY_AFTER_COST_RETURN: "
                f"{stability.after_cost_return} must be > "
                f"{gates.minimum_stability_after_cost_return_exclusive}"
            )
        if stressed is None:
            failures.append(
                "COST_STRESS_1_5X: exact 1.5x economics were not supplied; robustness gate unmet"
            )
        elif stressed.after_cost_return <= gates.minimum_stressed_after_cost_return_exclusive:
            failures.append(
                "COST_STRESS_1_5X_RETURN: "
                f"{stressed.after_cost_return} must be > "
                f"{gates.minimum_stressed_after_cost_return_exclusive}"
            )
        gates_passed = not failures
        return PromotionVerdict(
            status=(
                PromotionStatus.RESEARCH_GATES_PASSED_PROMOTION_BLOCKED
                if gates_passed
                else PromotionStatus.NOT_ELIGIBLE
            ),
            research_gates_passed=gates_passed,
            promotion_allowed=False,
            unmet_gates=tuple(failures),
            mandatory_next_evidence=(
                "Untouched prospective evidence is required; this history was already inspected.",
                "A separate forward IG Demo validation must pass before any promotion decision.",
                "Human review and an explicit promotion decision remain mandatory.",
            ),
        )


def aggregate_segments(segments: Sequence[SegmentResult]) -> AggregateMetrics:
    if not segments:
        raise ValueError("at least one segment is required for aggregation")
    returns = tuple(segment.metrics.total_return for segment in segments)
    ordered = sorted(returns)
    midpoint = len(ordered) // 2
    median = (
        ordered[midpoint]
        if len(ordered) % 2
        else (ordered[midpoint - 1] + ordered[midpoint]) / Decimal("2")
    )
    mean = sum(returns, ZERO) / Decimal(len(returns))
    variance = sum(((value - mean) ** 2 for value in returns), ZERO) / Decimal(len(returns))
    deviation = variance.sqrt()
    starting = money(sum((segment.metrics.starting_equity for segment in segments), ZERO))
    final = money(sum((segment.metrics.final_equity for segment in segments), ZERO))
    gross_profit = money(sum((segment.metrics.gross_profit for segment in segments), ZERO))
    gross_loss = money(sum((segment.metrics.gross_loss for segment in segments), ZERO))
    infinite_profit_factor = gross_loss == ZERO and gross_profit > ZERO
    profit_factor = None if gross_loss == ZERO else gross_profit / abs(gross_loss)
    return AggregateMetrics(
        fold_count=len(segments),
        starting_capital_total=starting,
        final_capital_total=final,
        after_cost_return=ZERO if starting == ZERO else (final - starting) / starting,
        mean_fold_return=mean,
        median_fold_return=median,
        fold_return_standard_deviation=deviation,
        positive_folds=sum(value > ZERO for value in returns),
        aggregate_trades=sum(segment.metrics.number_of_trades for segment in segments),
        folds_with_at_least_five_trades=sum(
            segment.metrics.number_of_trades >= 5 for segment in segments
        ),
        aggregate_gross_profit=gross_profit,
        aggregate_gross_loss=gross_loss,
        aggregate_profit_factor=profit_factor,
        profit_factor_is_infinite=infinite_profit_factor,
        total_execution_cost=money(
            sum((segment.total_execution_cost for segment in segments), ZERO)
        ),
        worst_fold_maximum_drawdown=max(segment.metrics.maximum_drawdown for segment in segments),
        any_ruin=any(segment.metrics.ruin_reached for segment in segments),
        performance_by_instrument=_breakdown_consistency(segments, "performance_by_instrument"),
        performance_by_regime=_breakdown_consistency(segments, "performance_by_regime"),
    )


def _breakdown_consistency(
    segments: Sequence[SegmentResult], attribute: str
) -> tuple[BreakdownConsistency, ...]:
    mappings = [getattr(segment.metrics, attribute) for segment in segments]
    keys = sorted({str(key) for mapping in mappings for key in mapping})
    output: list[BreakdownConsistency] = []
    for key in keys:
        values = tuple(mapping.get(key, ZERO) for mapping in mappings)
        mean = sum(values, ZERO) / Decimal(len(values))
        variance = sum(((value - mean) ** 2 for value in values), ZERO) / Decimal(len(values))
        output.append(
            BreakdownConsistency(
                key=key,
                aggregate_net_pnl=money(sum(values, ZERO)),
                profitable_folds=sum(value > ZERO for value in values),
                folds_present=sum(key in mapping for mapping in mappings),
                mean_fold_net_pnl=mean,
                fold_net_pnl_standard_deviation=variance.sqrt(),
            )
        )
    return tuple(output)


def _profit_factor_delta(
    stability_profit_factor: Decimal | None, test_profit_factor: Decimal | None
) -> Decimal | None:
    return _optional_delta(stability_profit_factor, test_profit_factor)


def _optional_delta(stability_value: Decimal | None, test_value: Decimal | None) -> Decimal | None:
    if stability_value is None or test_value is None:
        return None
    return test_value - stability_value


def degradation_summary(folds: Sequence[FoldResult]) -> StabilityDegradationSummary:
    if not folds:
        raise ValueError("at least one fold is required for a degradation summary")
    returns = tuple(fold.test_return_delta_vs_stability for fold in folds)
    mean = sum(returns, ZERO) / Decimal(len(returns))
    ordered = sorted(returns)
    midpoint = len(ordered) // 2
    median = (
        ordered[midpoint]
        if len(ordered) % 2
        else (ordered[midpoint - 1] + ordered[midpoint]) / Decimal("2")
    )
    variance = sum(((value - mean) ** 2 for value in returns), ZERO) / Decimal(len(returns))
    profit_factor_deltas = tuple(fold.test_profit_factor_delta_vs_stability for fold in folds)
    annualised_return_deltas = tuple(
        fold.test_annualised_return_delta_vs_stability for fold in folds
    )
    defined_annualised_return_deltas = tuple(
        value for value in annualised_return_deltas if value is not None
    )
    defined_profit_factor_deltas = tuple(
        value for value in profit_factor_deltas if value is not None
    )
    mean_profit_factor_delta = (
        None
        if not defined_profit_factor_deltas
        else sum(defined_profit_factor_deltas, ZERO) / Decimal(len(defined_profit_factor_deltas))
    )
    return StabilityDegradationSummary(
        return_deltas=returns,
        mean_return_delta=mean,
        median_return_delta=median,
        return_delta_standard_deviation=variance.sqrt(),
        non_degrading_return_folds=sum(value >= ZERO for value in returns),
        annualised_return_deltas=annualised_return_deltas,
        mean_defined_annualised_return_delta=(
            None
            if not defined_annualised_return_deltas
            else sum(defined_annualised_return_deltas, ZERO)
            / Decimal(len(defined_annualised_return_deltas))
        ),
        profit_factor_deltas=profit_factor_deltas,
        mean_defined_profit_factor_delta=mean_profit_factor_delta,
    )
