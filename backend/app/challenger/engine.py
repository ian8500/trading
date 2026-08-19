from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from app.core.clock import ensure_utc
from app.core.decimal import ZERO, as_decimal
from app.opportunities import OpportunityCandidate


@dataclass(frozen=True, slots=True)
class ChallengerConfig:
    minimum_revised_score: Decimal = Decimal("0")
    minimum_reward_risk: Decimal = Decimal("1.25")
    maximum_age: timedelta = timedelta(hours=2)
    maximum_recent_move: Decimal = Decimal("0.04")
    maximum_spread_fraction: Decimal = Decimal("0.005")
    minimum_liquidity: Decimal = Decimal("0.40")
    minimum_historical_support: int = 30
    minimum_data_quality: Decimal = Decimal("0.70")


@dataclass(frozen=True, slots=True)
class ChallengeContext:
    now: datetime
    recent_move: Decimal = ZERO
    nearby_high_impact_event: bool = False
    contradictory_related_market: bool = False
    duplicate_directional_exposure: bool = False
    excessive_correlation: bool = False
    strategy_degraded: bool = False
    out_of_distribution: bool = False
    suitable_market_hours: bool = True
    weekend_or_close_risk: bool = False
    minimum_size_too_risky: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "now", ensure_utc(self.now))
        object.__setattr__(self, "recent_move", as_decimal(self.recent_move))


@dataclass(frozen=True, slots=True)
class ChallengeResult:
    original_score: Decimal
    supporting_factors: tuple[str, ...]
    penalties: dict[str, Decimal]
    revised_score: Decimal
    approved: bool
    rejection_reasons: tuple[str, ...]


class DeterministicChallenger:
    def __init__(self, config: ChallengerConfig | None = None) -> None:
        self.config = config or ChallengerConfig()

    def challenge(
        self,
        candidate: OpportunityCandidate,
        context: ChallengeContext,
    ) -> ChallengeResult:
        cfg = self.config
        original = candidate.score
        supporting: list[str] = []
        penalties: dict[str, Decimal] = {}
        reasons: list[str] = []

        def reject(key: str, reason: str, penalty: str = "0.10") -> None:
            penalties[key] = Decimal(penalty)
            reasons.append(reason)

        age = context.now - candidate.timestamp
        if age.total_seconds() < 0 or age > cfg.maximum_age:
            reject("stale_signal", "signal is stale or timestamp is anomalous", "0.25")
        else:
            supporting.append("signal timestamp is current")
        if abs(context.recent_move) > cfg.maximum_recent_move:
            reject("late_entry", "recent move is excessively extended")
        if candidate.reward_risk_ratio < cfg.minimum_reward_risk:
            reject("reward_risk", "reward-to-risk ratio is below minimum", "0.25")
        else:
            supporting.append("reward-to-risk clears threshold")
        if candidate.spread_fraction > cfg.maximum_spread_fraction:
            reject("spread", "spread is abnormal", "0.20")
        if candidate.liquidity_score < cfg.minimum_liquidity:
            reject("liquidity", "liquidity score is too low")
        if candidate.historical_support < cfg.minimum_historical_support:
            penalties["historical_support"] = Decimal("0.003")
        else:
            supporting.append("historical support is sufficient")
        if candidate.data_quality < cfg.minimum_data_quality:
            reject("data_quality", "data quality is below minimum", "0.20")
        flag_checks = (
            (context.nearby_high_impact_event, "event_risk", "nearby high-impact event"),
            (
                context.contradictory_related_market,
                "contradiction",
                "related market contradicts thesis",
            ),
            (
                context.duplicate_directional_exposure,
                "duplicate_exposure",
                "duplicate directional exposure",
            ),
            (context.excessive_correlation, "correlation", "correlated exposure is excessive"),
            (context.strategy_degraded, "strategy_health", "strategy performance is degraded"),
            (context.out_of_distribution, "distribution", "market is out of distribution"),
            (not context.suitable_market_hours, "market_hours", "market hours are unsuitable"),
            (context.weekend_or_close_risk, "weekend_close", "weekend or market-close risk"),
            (
                context.minimum_size_too_risky,
                "minimum_size",
                "minimum deal size exceeds risk limit",
            ),
        )
        for active, key, reason in flag_checks:
            if active:
                reject(key, reason)
        revised = original - sum(penalties.values(), ZERO)
        approved = not reasons and revised >= cfg.minimum_revised_score
        if revised < cfg.minimum_revised_score:
            reasons.append("revised score is below execution threshold")
        return ChallengeResult(
            original,
            tuple(supporting),
            penalties,
            revised,
            approved,
            tuple(reasons),
        )
