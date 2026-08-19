from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from enum import StrEnum

from app.core.decimal import ZERO, as_decimal
from app.opportunities import OpportunityCandidate


class RiskProfile(StrEnum):
    CONSERVATIVE = "Conservative"
    STANDARD = "Standard"
    AGGRESSIVE = "Aggressive"
    EXPERIMENTAL = "Experimental"
    CUSTOM = "Custom"


class StrategyHealth(StrEnum):
    NORMAL = "NORMAL"
    REDUCED_RISK = "REDUCED_RISK"
    SUSPENDED = "SUSPENDED"
    OBSERVATION_ONLY = "OBSERVATION_ONLY"


@dataclass(frozen=True, slots=True)
class RiskLimits:
    profile: RiskProfile = RiskProfile.STANDARD
    risk_per_trade: Decimal = Decimal("0.02")
    max_open_risk: Decimal = Decimal("0.06")
    max_market_exposure: Decimal = Decimal("3.00")
    max_effective_leverage: Decimal = Decimal("3.0")
    max_margin_usage: Decimal = Decimal("0.50")
    max_correlated_risk: Decimal = Decimal("0.04")
    max_concurrent_positions: int = 3
    max_daily_loss: Decimal = Decimal("0.05")
    max_weekly_loss: Decimal = Decimal("0.10")
    max_rolling_drawdown: Decimal = Decimal("0.15")
    max_total_drawdown: Decimal = Decimal("0.30")
    min_reward_risk: Decimal = Decimal("1.25")
    max_spread_fraction: Decimal = Decimal("0.005")
    max_data_age: timedelta = timedelta(hours=2)
    min_data_quality: Decimal = Decimal("0.70")

    def __post_init__(self) -> None:
        object.__setattr__(self, "profile", RiskProfile(self.profile))
        for name in (
            "risk_per_trade",
            "max_open_risk",
            "max_market_exposure",
            "max_effective_leverage",
            "max_margin_usage",
            "max_correlated_risk",
            "max_daily_loss",
            "max_weekly_loss",
            "max_rolling_drawdown",
            "max_total_drawdown",
            "min_reward_risk",
            "max_spread_fraction",
            "min_data_quality",
        ):
            object.__setattr__(self, name, as_decimal(getattr(self, name)))
        if self.risk_per_trade <= ZERO:
            raise ValueError("risk_per_trade must be positive")


def limits_for_profile(profile: RiskProfile | str) -> RiskLimits:
    profile = RiskProfile(profile)
    risk = {
        RiskProfile.CONSERVATIVE: Decimal("0.01"),
        RiskProfile.STANDARD: Decimal("0.02"),
        RiskProfile.AGGRESSIVE: Decimal("0.04"),
        RiskProfile.EXPERIMENTAL: Decimal("0.06"),
    }
    if profile is RiskProfile.CUSTOM:
        raise ValueError("Custom profile requires explicit RiskLimits")
    per_trade = risk[profile]
    return RiskLimits(
        profile=profile,
        risk_per_trade=per_trade,
        max_open_risk=per_trade * Decimal("3"),
        max_correlated_risk=per_trade * Decimal("2"),
    )


@dataclass(frozen=True, slots=True)
class RiskDecision:
    decision_id: str
    approved: bool
    reasons: tuple[str, ...]
    equity_basis: Decimal
    risk_fraction: Decimal
    permitted_risk: Decimal
    position_size: Decimal
    planned_monetary_risk: Decimal
    notional: Decimal
    margin_required: Decimal


@dataclass(frozen=True, slots=True)
class ApprovedOrder:
    """Capability object required by every simulated or real broker boundary."""

    candidate: OpportunityCandidate
    decision: RiskDecision
    stop_distance: Decimal
    target_distance: Decimal | None

    def __post_init__(self) -> None:
        if not self.decision.approved:
            raise ValueError("an ApprovedOrder requires an approved RiskDecision")
