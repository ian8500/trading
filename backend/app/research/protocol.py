"""Frozen retrospective walk-forward research protocol.

The dates and gates in this module are deliberately code, rather than CLI
options.  Changing any of them creates a different protocol fingerprint and
requires a new protocol version before results may be compared.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.backtesting.costs import CostPreset
from app.backtesting.engine import BacktestConfig
from app.backtesting.fingerprint import SIMULATOR_BEHAVIOR_VERSION, research_fingerprint
from app.backtesting.models import FillPolicy
from app.instruments.catalog import OFFICIAL_DAILY_SYMBOLS
from app.risk import RiskProfile

from .provenance import STRATEGY_IMPLEMENTATION_PROVENANCE_SCHEMA

RETROSPECTIVE_LABEL = "RETROSPECTIVE_PSEUDO_OOS"
_IMPLEMENTATION_DIGEST = "f00f248c32b056a51cd3d710e9d1cde1dbfb17d0f186a55622afb2c7812e76b8"  # pragma: allowlist secret  # noqa: E501


def _utc(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=UTC)


HISTORY_START = _utc(2018, 1, 1)
HISTORY_END = _utc(2026, 8, 19)


@dataclass(frozen=True, slots=True)
class StrategySpecification:
    """An immutable strategy/risk pairing declared before evaluation."""

    key: str
    display_name: str
    version_prefix: str
    risk_profile: RiskProfile
    parameter_fingerprint: str


_QUANT_BASELINE_PARAMETER_FINGERPRINT = (
    "53ca9196b585037f2a5145111ee4297de520df165aae30a66da769f631177083"  # pragma: allowlist secret
)
_QUANT_AGGRESSIVE_PARAMETER_FINGERPRINT = (
    "974890d2391649c8e69096007e833a1894d9f213fe8f5770b70cfa4d01f4a761"  # pragma: allowlist secret
)
_REGIME_ENSEMBLE_PARAMETER_FINGERPRINT = (
    "531b549b2f382bf76c9f0aea1b23dda2f322cf862819ca96e1efad6345d55d03"  # pragma: allowlist secret
)


PREDECLARED_STRATEGIES = (
    StrategySpecification(
        key="quant-baseline",
        display_name="Quant Baseline",
        version_prefix="quant-baseline-v1",
        risk_profile=RiskProfile.STANDARD,
        parameter_fingerprint=_QUANT_BASELINE_PARAMETER_FINGERPRINT,
    ),
    StrategySpecification(
        key="quant-aggressive",
        display_name="Quant Aggressive",
        version_prefix="quant-aggressive-v1",
        risk_profile=RiskProfile.AGGRESSIVE,
        parameter_fingerprint=_QUANT_AGGRESSIVE_PARAMETER_FINGERPRINT,
    ),
    StrategySpecification(
        key="regime-ensemble",
        display_name="Regime Ensemble",
        version_prefix="regime-ensemble-v1",
        risk_profile=RiskProfile.STANDARD,
        parameter_fingerprint=_REGIME_ENSEMBLE_PARAMETER_FINGERPRINT,
    ),
)


@dataclass(frozen=True, slots=True)
class EligibilityGates:
    required_fold_count: int = 5
    require_all_folds_reproducible: bool = True
    minimum_aggregate_after_cost_return_exclusive: Decimal = Decimal("0")
    minimum_aggregate_profit_factor: Decimal = Decimal("1.10")
    minimum_median_fold_return_exclusive: Decimal = Decimal("0")
    minimum_positive_folds: int = 3
    minimum_aggregate_trades: int = 50
    minimum_trades_per_counted_fold: int = 5
    minimum_folds_with_enough_trades: int = 4
    maximum_worst_fold_drawdown: Decimal = Decimal("0.15")
    require_no_ruin: bool = True
    minimum_stability_after_cost_return_exclusive: Decimal = Decimal("0")
    required_cost_stress_multiplier: Decimal = Decimal("1.5")
    minimum_stressed_after_cost_return_exclusive: Decimal = Decimal("0")


@dataclass(frozen=True, slots=True)
class FoldBoundary:
    """One anchored train / stability / test split.

    Every interval is half-open: ``start <= timestamp < end``. The final
    predeclared exclusive end is 2026-08-19T00:00Z; the cached daily
    manifests contain completed observations only through 2026-08-18.
    """

    fold_id: str
    label: str
    train_start: datetime
    train_end: datetime
    stability_start: datetime
    stability_end: datetime
    test_start: datetime
    test_end: datetime

    def __post_init__(self) -> None:
        timestamps = (
            self.train_start,
            self.train_end,
            self.stability_start,
            self.stability_end,
            self.test_start,
            self.test_end,
        )
        if any(value.tzinfo is None or value.utcoffset() is None for value in timestamps):
            raise ValueError("fold boundaries must be timezone-aware")
        if self.label != RETROSPECTIVE_LABEL:
            raise ValueError(f"every fold must be labelled {RETROSPECTIVE_LABEL}")
        if self.train_start >= self.train_end:
            raise ValueError("training interval must be non-empty")
        if self.train_end != self.stability_start:
            raise ValueError("stability must begin immediately after the anchored training window")
        if self.stability_start >= self.stability_end:
            raise ValueError("stability interval must be non-empty")
        if self.stability_end != self.test_start:
            raise ValueError("test must begin immediately after the stability window")
        if self.test_start >= self.test_end:
            raise ValueError("test interval must be non-empty")


FROZEN_FOLDS = (
    FoldBoundary(
        "fold-1",
        RETROSPECTIVE_LABEL,
        _utc(2018, 1, 1),
        _utc(2021, 1, 1),
        _utc(2021, 1, 1),
        _utc(2022, 1, 1),
        _utc(2022, 1, 1),
        _utc(2023, 1, 1),
    ),
    FoldBoundary(
        "fold-2",
        RETROSPECTIVE_LABEL,
        _utc(2018, 1, 1),
        _utc(2022, 1, 1),
        _utc(2022, 1, 1),
        _utc(2023, 1, 1),
        _utc(2023, 1, 1),
        _utc(2024, 1, 1),
    ),
    FoldBoundary(
        "fold-3",
        RETROSPECTIVE_LABEL,
        _utc(2018, 1, 1),
        _utc(2023, 1, 1),
        _utc(2023, 1, 1),
        _utc(2024, 1, 1),
        _utc(2024, 1, 1),
        _utc(2025, 1, 1),
    ),
    FoldBoundary(
        "fold-4",
        RETROSPECTIVE_LABEL,
        _utc(2018, 1, 1),
        _utc(2024, 1, 1),
        _utc(2024, 1, 1),
        _utc(2025, 1, 1),
        _utc(2025, 1, 1),
        _utc(2026, 1, 1),
    ),
    FoldBoundary(
        "fold-5",
        RETROSPECTIVE_LABEL,
        _utc(2018, 1, 1),
        _utc(2025, 1, 1),
        _utc(2025, 1, 1),
        _utc(2026, 1, 1),
        _utc(2026, 1, 1),
        _utc(2026, 8, 19),
    ),
)


@dataclass(frozen=True, slots=True)
class ResearchProtocol:
    protocol_id: str = "nine-market-anchored-walk-forward"
    protocol_version: str = "1.2.0"
    label: str = RETROSPECTIVE_LABEL
    history_start: datetime = HISTORY_START
    history_end: datetime = HISTORY_END
    interval: str = "1d"
    provider: str = "Yahoo Finance"
    research_cost_schedule_id: str = "instrument-research-costs-v1"
    cost_stress_scenario_id: str = "realistic-costs-x1.5-v1"
    conversion_policy_id: str = "quote-to-gbp-v1"
    conversion_timing_policy_id: str = "modeled-bar-open-conversion-v1"
    fill_risk_revalidation_policy_id: str = "fill-risk-revalidation-v1-reservation-capped"
    session_policy_id: str = "research-market-sessions-v1"
    simulator_behavior_version: str = "historical-simulator-v4-modeled-open-fx"
    strategy_implementation_provenance_schema: str = STRATEGY_IMPLEMENTATION_PROVENANCE_SCHEMA
    strategy_implementation_digest: str = _IMPLEMENTATION_DIGEST
    symbols: tuple[str, ...] = OFFICIAL_DAILY_SYMBOLS
    starting_equity: Decimal = Decimal("500.00")
    cost_preset: CostPreset = CostPreset.REALISTIC
    fill_policy: FillPolicy = FillPolicy.CONSERVATIVE
    maximum_holding_bars: int = 2
    execution_delay_bars: int = 1
    seed: int = 8500
    risk_taper: bool = False
    warmup_calendar_days: int = 400
    minimum_warmup_bars_per_market: int = 60
    minimum_business_day_coverage: Decimal = Decimal("0.85")
    maximum_boundary_lag_days: int = 10
    folds: tuple[FoldBoundary, ...] = FROZEN_FOLDS
    strategies: tuple[StrategySpecification, ...] = PREDECLARED_STRATEGIES
    gates: EligibilityGates = EligibilityGates()

    def __post_init__(self) -> None:
        if (
            self.protocol_id,
            self.protocol_version,
            self.label,
            self.history_start,
            self.history_end,
            self.interval,
            self.provider,
            self.starting_equity,
            self.cost_preset,
            self.fill_policy,
            self.maximum_holding_bars,
            self.execution_delay_bars,
            self.seed,
            self.risk_taper,
            self.warmup_calendar_days,
            self.minimum_warmup_bars_per_market,
            self.minimum_business_day_coverage,
            self.maximum_boundary_lag_days,
        ) != (
            "nine-market-anchored-walk-forward",
            "1.2.0",
            RETROSPECTIVE_LABEL,
            HISTORY_START,
            HISTORY_END,
            "1d",
            "Yahoo Finance",
            Decimal("500.00"),
            CostPreset.REALISTIC,
            FillPolicy.CONSERVATIVE,
            2,
            1,
            8500,
            False,
            400,
            60,
            Decimal("0.85"),
            10,
        ):
            raise ValueError("research protocol scalar configuration is frozen")
        if self.label != RETROSPECTIVE_LABEL:
            raise ValueError(f"protocol label must be {RETROSPECTIVE_LABEL}")
        if self.interval != "1d":
            raise ValueError("the frozen protocol requires daily bars")
        if (
            self.research_cost_schedule_id,
            self.cost_stress_scenario_id,
            self.conversion_policy_id,
            self.conversion_timing_policy_id,
            self.fill_risk_revalidation_policy_id,
            self.session_policy_id,
            self.simulator_behavior_version,
        ) != (
            "instrument-research-costs-v1",
            "realistic-costs-x1.5-v1",
            "quote-to-gbp-v1",
            "modeled-bar-open-conversion-v1",
            "fill-risk-revalidation-v1-reservation-capped",
            "research-market-sessions-v1",
            "historical-simulator-v4-modeled-open-fx",
        ):
            raise ValueError("research economics and policy identifiers are frozen")
        if self.simulator_behavior_version != SIMULATOR_BEHAVIOR_VERSION:
            raise ValueError("frozen protocol simulator behavior does not match the engine")
        if (
            self.strategy_implementation_provenance_schema,
            self.strategy_implementation_digest,
        ) != (
            STRATEGY_IMPLEMENTATION_PROVENANCE_SCHEMA,
            _IMPLEMENTATION_DIGEST,
        ):
            raise ValueError("strategy implementation provenance is frozen")
        if self.symbols != OFFICIAL_DAILY_SYMBOLS:
            raise ValueError("the frozen protocol requires the official nine-market universe")
        if self.starting_equity != Decimal("500.00"):
            raise ValueError("the frozen protocol requires £500 starting capital")
        if self.cost_preset is not CostPreset.REALISTIC:
            raise ValueError("the frozen protocol requires the REALISTIC after-cost model")
        if self.fill_policy is not FillPolicy.CONSERVATIVE:
            raise ValueError("the frozen protocol requires conservative ambiguous-bar fills")
        if self.folds != FROZEN_FOLDS:
            raise ValueError("fold boundaries are frozen and cannot be supplied at runtime")
        if self.strategies != PREDECLARED_STRATEGIES:
            raise ValueError("strategy roster and versions are frozen")
        if self.gates != EligibilityGates():
            raise ValueError("eligibility gates are frozen and cannot be supplied at runtime")
        if len(self.folds) != self.gates.required_fold_count:
            raise ValueError("the frozen protocol requires exactly five folds")
        if len({fold.fold_id for fold in self.folds}) != len(self.folds):
            raise ValueError("fold identifiers must be unique")
        if self.history_start != self.folds[0].train_start:
            raise ValueError("history must begin at the anchored training origin")
        if self.history_end != self.folds[-1].test_end:
            raise ValueError("history must end at the final test boundary")
        for index, fold in enumerate(self.folds):
            expected_test_year = 2022 + index
            if fold.train_start != self.history_start:
                raise ValueError("every training window must remain anchored at 2018-01-01")
            if fold.train_end.year != 2021 + index or fold.train_end.month != 1:
                raise ValueError("training endpoints must expand in exact one-year steps")
            if fold.stability_start != fold.train_end:
                raise ValueError("each stability fold must be nested after its training window")
            expected_stability_end = _utc(2022 + index, 1, 1)
            if fold.stability_end != expected_stability_end:
                raise ValueError("stability folds must be exact predeclared calendar years")
            if fold.test_start != _utc(expected_test_year, 1, 1):
                raise ValueError("test folds must advance in exact one-year steps")
            if index < len(self.folds) - 1 and fold.test_end != _utc(expected_test_year + 1, 1, 1):
                raise ValueError("completed test folds must span one calendar year")
            if index and self.folds[index - 1].test_end != fold.test_start:
                raise ValueError("test folds must be chronological and contiguous")
        if self.warmup_calendar_days < 1 or self.minimum_warmup_bars_per_market < 1:
            raise ValueError("causal warm-up requirements must be positive")
        if not Decimal("0") < self.minimum_business_day_coverage <= Decimal("1"):
            raise ValueError("minimum business-day data coverage must be in (0, 1]")
        if self.maximum_boundary_lag_days < 1:
            raise ValueError("maximum data boundary lag must be positive")

    @property
    def backtest_config(self) -> BacktestConfig:
        return BacktestConfig(
            starting_equity=self.starting_equity,
            cost_preset=self.cost_preset,
            fill_policy=self.fill_policy,
            execution_delay_bars=self.execution_delay_bars,
            maximum_holding_bars=self.maximum_holding_bars,
            seed=self.seed,
            bar_interval=self.interval,
        )

    def warmup_start(self, segment_start: datetime) -> datetime:
        return max(self.history_start, segment_start - timedelta(days=self.warmup_calendar_days))

    @property
    def fingerprint(self) -> str:
        return research_fingerprint({"kind": "research_protocol", "protocol": self})


FROZEN_PROTOCOL = ResearchProtocol()
