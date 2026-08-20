"""Typed outputs for the frozen retrospective research protocol."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum, StrEnum
from typing import Any

from app.backtesting.costs import CostPreset
from app.backtesting.fingerprint import research_fingerprint
from app.backtesting.metrics import BacktestMetrics
from app.backtesting.models import Bar
from app.backtesting.research_costs import ResearchCostAssumption

from .provenance import StrategyImplementationProvenance


class SegmentKind(StrEnum):
    STABILITY = "STABILITY"
    TEST = "TEST"
    COST_STRESS_TEST = "COST_STRESS_TEST"


class PromotionStatus(StrEnum):
    NOT_ELIGIBLE = "NOT_ELIGIBLE"
    RESEARCH_GATES_PASSED_PROMOTION_BLOCKED = "RESEARCH_GATES_PASSED_PROMOTION_BLOCKED"


@dataclass(frozen=True, slots=True)
class DataSnapshot:
    provider: str
    interval: str
    window_start: datetime
    window_end: datetime
    symbols: tuple[str, ...]
    manifest_checksums: tuple[tuple[str, str], ...]
    manifest_ids: tuple[tuple[str, str], ...]
    manifest_declared_row_counts: tuple[tuple[str, int], ...]
    manifest_missing_intervals: tuple[tuple[str, int], ...]
    manifest_start_at: tuple[tuple[str, datetime], ...]
    manifest_end_at: tuple[tuple[str, datetime], ...]
    row_counts: tuple[tuple[str, int], ...]
    first_bar_at: tuple[tuple[str, datetime], ...]
    last_bar_at: tuple[tuple[str, datetime], ...]
    bar_payload_fingerprint: str

    @classmethod
    def from_bars(
        cls,
        *,
        provider: str,
        interval: str,
        window_start: datetime,
        window_end: datetime,
        bars_by_instrument: Mapping[str, Sequence[Bar]],
        manifest_checksums: Mapping[str, str],
        manifest_ids: Mapping[str, str] | None = None,
        manifest_declared_row_counts: Mapping[str, int] | None = None,
        manifest_missing_intervals: Mapping[str, int] | None = None,
        manifest_start_at: Mapping[str, datetime] | None = None,
        manifest_end_at: Mapping[str, datetime] | None = None,
    ) -> DataSnapshot:
        symbols = tuple(sorted(bars_by_instrument))
        if set(manifest_checksums) != set(symbols):
            raise ValueError("one manifest checksum is required for every market")
        if manifest_ids is not None and set(manifest_ids) != set(symbols):
            raise ValueError("manifest identifiers must cover every market")
        normalized = {
            symbol: tuple(sorted(bars_by_instrument[symbol], key=lambda bar: bar.timestamp))
            for symbol in symbols
        }
        if any(not bars for bars in normalized.values()):
            raise ValueError("every market requires at least one completed bar")
        if any(
            bar.timestamp < window_start or bar.timestamp >= window_end
            for bars in normalized.values()
            for bar in bars
        ):
            raise ValueError("data snapshot contains a bar outside its declared window")
        actual_counts = {symbol: len(normalized[symbol]) for symbol in symbols}
        actual_starts = {symbol: normalized[symbol][0].timestamp for symbol in symbols}
        actual_ends = {symbol: normalized[symbol][-1].timestamp for symbol in symbols}
        declared_counts = dict(manifest_declared_row_counts or actual_counts)
        missing_intervals = dict(manifest_missing_intervals or {symbol: 0 for symbol in symbols})
        declared_starts = dict(manifest_start_at or actual_starts)
        declared_ends = dict(manifest_end_at or actual_ends)
        for name, values in (
            ("declared row counts", declared_counts),
            ("missing intervals", missing_intervals),
            ("manifest starts", declared_starts),
            ("manifest ends", declared_ends),
        ):
            if set(values) != set(symbols):
                raise ValueError(f"manifest {name} must cover every market")
        if declared_counts != actual_counts:
            raise ValueError("manifest row counts do not match completed database bars")
        if declared_starts != actual_starts or declared_ends != actual_ends:
            raise ValueError("manifest range does not match completed database bars")
        if any(value < 0 for value in missing_intervals.values()):
            raise ValueError("manifest missing-interval counts cannot be negative")
        return cls(
            provider=provider,
            interval=interval,
            window_start=window_start,
            window_end=window_end,
            symbols=symbols,
            manifest_checksums=tuple(sorted(manifest_checksums.items())),
            manifest_ids=tuple(sorted((manifest_ids or {}).items())),
            manifest_declared_row_counts=tuple(sorted(declared_counts.items())),
            manifest_missing_intervals=tuple(sorted(missing_intervals.items())),
            manifest_start_at=tuple(sorted(declared_starts.items())),
            manifest_end_at=tuple(sorted(declared_ends.items())),
            row_counts=tuple(sorted(actual_counts.items())),
            first_bar_at=tuple((symbol, normalized[symbol][0].timestamp) for symbol in symbols),
            last_bar_at=tuple((symbol, normalized[symbol][-1].timestamp) for symbol in symbols),
            bar_payload_fingerprint=research_fingerprint(
                {"kind": "completed_bar_payload", "bars_by_instrument": normalized}
            ),
        )

    @property
    def fingerprint(self) -> str:
        # Database row identifiers are deployment-local provenance pointers,
        # not properties of the source observations.  Keeping them outside the
        # canonical payload makes identical imports portable across databases.
        canonical_payload = {
            "provider": self.provider,
            "interval": self.interval,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "symbols": self.symbols,
            "manifest_checksums": self.manifest_checksums,
            "manifest_declared_row_counts": self.manifest_declared_row_counts,
            "manifest_missing_intervals": self.manifest_missing_intervals,
            "manifest_start_at": self.manifest_start_at,
            "manifest_end_at": self.manifest_end_at,
            "row_counts": self.row_counts,
            "first_bar_at": self.first_bar_at,
            "last_bar_at": self.last_bar_at,
            "bar_payload_fingerprint": self.bar_payload_fingerprint,
        }
        return research_fingerprint({"kind": "data_snapshot", "snapshot": canonical_payload})


@dataclass(frozen=True, slots=True)
class CostStressScenario:
    """Required exact cost-assumption scaling supplied by the economics layer."""

    name: str
    multiplier: Decimal
    cost_assumptions: Mapping[str, ResearchCostAssumption]

    def __post_init__(self) -> None:
        if self.multiplier != Decimal("1.5"):
            raise ValueError("the frozen robustness gate requires an exact 1.5x cost scenario")
        object.__setattr__(
            self,
            "cost_assumptions",
            dict(sorted(self.cost_assumptions.items())),
        )

    @property
    def fingerprint(self) -> str:
        return research_fingerprint({"kind": "cost_stress_scenario", "scenario": self})


@dataclass(frozen=True, slots=True)
class SegmentResult:
    fold_id: str
    label: str
    kind: SegmentKind
    start: datetime
    end: datetime
    warmup_start: datetime
    warmup_bar_counts: dict[str, int]
    evaluation_bar_counts: dict[str, int]
    reference_bar_counts: dict[str, int]
    cost_preset: CostPreset
    cost_scenario: str
    metrics: BacktestMetrics
    total_execution_cost: Decimal
    engine_run_fingerprint: str
    outcome_fingerprint: str
    repeated_outcome_fingerprint: str | None
    reproducibility_checked: bool
    reproducible: bool
    causal_guard_passed: bool
    strategy_versions: dict[str, str]
    segment_fingerprint: str


@dataclass(frozen=True, slots=True)
class FoldResult:
    fold_id: str
    label: str
    train_start: datetime
    train_end: datetime
    stability: SegmentResult
    test: SegmentResult
    stressed_test: SegmentResult
    test_return_delta_vs_stability: Decimal
    test_annualised_return_delta_vs_stability: Decimal | None
    test_profit_factor_delta_vs_stability: Decimal | None
    fold_fingerprint: str


@dataclass(frozen=True, slots=True)
class BreakdownConsistency:
    key: str
    aggregate_net_pnl: Decimal
    profitable_folds: int
    folds_present: int
    mean_fold_net_pnl: Decimal
    fold_net_pnl_standard_deviation: Decimal


@dataclass(frozen=True, slots=True)
class AggregateMetrics:
    fold_count: int
    starting_capital_total: Decimal
    final_capital_total: Decimal
    after_cost_return: Decimal
    mean_fold_return: Decimal
    median_fold_return: Decimal
    fold_return_standard_deviation: Decimal
    positive_folds: int
    aggregate_trades: int
    folds_with_at_least_five_trades: int
    aggregate_gross_profit: Decimal
    aggregate_gross_loss: Decimal
    aggregate_profit_factor: Decimal | None
    profit_factor_is_infinite: bool
    total_execution_cost: Decimal
    worst_fold_maximum_drawdown: Decimal
    any_ruin: bool
    performance_by_instrument: tuple[BreakdownConsistency, ...]
    performance_by_regime: tuple[BreakdownConsistency, ...]


@dataclass(frozen=True, slots=True)
class StabilityDegradationSummary:
    return_deltas: tuple[Decimal, ...]
    mean_return_delta: Decimal
    median_return_delta: Decimal
    return_delta_standard_deviation: Decimal
    non_degrading_return_folds: int
    annualised_return_deltas: tuple[Decimal | None, ...]
    mean_defined_annualised_return_delta: Decimal | None
    profit_factor_deltas: tuple[Decimal | None, ...]
    mean_defined_profit_factor_delta: Decimal | None


@dataclass(frozen=True, slots=True)
class PromotionVerdict:
    status: PromotionStatus
    research_gates_passed: bool
    promotion_allowed: bool
    unmet_gates: tuple[str, ...]
    mandatory_next_evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StrategyResearchResult:
    strategy_key: str
    strategy_name: str
    strategy_implementation_digest: str
    strategy_fingerprint: str
    per_market_strategy_fingerprints: dict[str, str]
    parameter_state_stable: bool
    config_fingerprint: str
    economics_fingerprint: str
    folds: tuple[FoldResult, ...]
    test_aggregate: AggregateMetrics
    stability_aggregate: AggregateMetrics
    stressed_test_aggregate: AggregateMetrics
    stability_to_test_degradation: StabilityDegradationSummary
    verdict: PromotionVerdict
    result_fingerprint: str


@dataclass(frozen=True, slots=True)
class ResearchProtocolReport:
    protocol_id: str
    protocol_version: str
    label: str
    disclosure: str
    protocol_fingerprint: str
    source_fingerprint: str
    data_fingerprint: str
    strategy_implementation_provenance: StrategyImplementationProvenance
    data_snapshot: DataSnapshot
    strategy_results: tuple[StrategyResearchResult, ...]
    report_fingerprint: str


def json_value(value: Any) -> Any:
    """Convert a report to stable, lossless JSON-friendly values."""

    if is_dataclass(value) and not isinstance(value, type):
        return json_value(asdict(value))
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [json_value(item) for item in value]
    return value
