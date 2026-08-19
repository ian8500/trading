from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any

from app.core.clock import ensure_utc
from app.core.decimal import ONE, ZERO, as_decimal


class Direction(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"

    @property
    def multiplier(self) -> Decimal:
        return ONE if self is Direction.LONG else Decimal("-1")


class ConfidenceState(StrEnum):
    CALIBRATED = "CALIBRATED"
    UNCALIBRATED = "UNCALIBRATED"


@dataclass(frozen=True, slots=True)
class ExpectedGrowthScore:
    """Inspectible components of a comparable geometric-growth score."""

    expected_log_growth: Decimal
    confidence_factor: Decimal
    regime_factor: Decimal
    data_quality_factor: Decimal
    strategy_health_factor: Decimal
    cost_penalty: Decimal
    tail_risk_penalty: Decimal
    correlation_penalty: Decimal
    event_risk_penalty: Decimal
    uncertainty_penalty: Decimal
    total: Decimal

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            object.__setattr__(self, name, as_decimal(getattr(self, name)))


@dataclass(frozen=True, slots=True)
class OpportunityCandidate:
    timestamp: datetime
    instrument_id: str
    strategy_version_id: str
    direction: Direction
    signal_price: Decimal
    expected_horizon: timedelta
    raw_signal_score: Decimal
    calibrated_probability: Decimal | None
    expected_upside: Decimal
    expected_downside: Decimal
    reward_risk_ratio: Decimal
    estimated_spread_cost: Decimal = ZERO
    estimated_slippage: Decimal = ZERO
    estimated_financing: Decimal = ZERO
    estimated_total_cost: Decimal = ZERO
    volatility: Decimal = ZERO
    liquidity_score: Decimal = ONE
    regime: str = "UNKNOWN"
    regime_suitability: Decimal = ONE
    historical_support: int = 0
    data_quality: Decimal = ONE
    strategy_health: Decimal = ONE
    correlation_penalty: Decimal = ZERO
    event_risk_penalty: Decimal = ZERO
    uncertainty_penalty: Decimal = ZERO
    tail_risk_penalty: Decimal = ZERO
    expected_growth_score: ExpectedGrowthScore | None = None
    structured_explanation: dict[str, Any] = field(default_factory=dict)
    proposed_stop_distance: Decimal | None = None
    proposed_target_distance: Decimal | None = None
    requested_risk_fraction: Decimal | None = None
    correlation_cluster: str | None = None
    market_open: bool = True
    spread_fraction: Decimal = ZERO

    def __post_init__(self) -> None:
        object.__setattr__(self, "timestamp", ensure_utc(self.timestamp))
        object.__setattr__(self, "direction", Direction(self.direction))
        decimal_fields = (
            "signal_price",
            "raw_signal_score",
            "expected_upside",
            "expected_downside",
            "reward_risk_ratio",
            "estimated_spread_cost",
            "estimated_slippage",
            "estimated_financing",
            "estimated_total_cost",
            "volatility",
            "liquidity_score",
            "regime_suitability",
            "data_quality",
            "strategy_health",
            "correlation_penalty",
            "event_risk_penalty",
            "uncertainty_penalty",
            "tail_risk_penalty",
            "spread_fraction",
        )
        for name in decimal_fields:
            object.__setattr__(self, name, as_decimal(getattr(self, name)))
        for name in (
            "calibrated_probability",
            "proposed_stop_distance",
            "proposed_target_distance",
            "requested_risk_fraction",
        ):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, as_decimal(value))
        if self.signal_price <= ZERO:
            raise ValueError("signal_price must be positive")
        if self.expected_upside < ZERO or self.expected_downside <= ZERO:
            raise ValueError("expected upside cannot be negative and downside must be positive")
        if (
            self.calibrated_probability is not None
            and not ZERO <= self.calibrated_probability <= ONE
        ):
            raise ValueError("calibrated_probability must be between zero and one")

    @property
    def confidence_state(self) -> ConfidenceState:
        return (
            ConfidenceState.CALIBRATED
            if self.calibrated_probability is not None
            else ConfidenceState.UNCALIBRATED
        )

    @property
    def score(self) -> Decimal:
        return (
            self.expected_growth_score.total
            if self.expected_growth_score
            else self.raw_signal_score
        )

    def with_growth_score(self, score: ExpectedGrowthScore) -> OpportunityCandidate:
        return replace(self, expected_growth_score=score)
