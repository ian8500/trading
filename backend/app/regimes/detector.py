from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from app.backtesting.models import Bar
from app.core.decimal import ONE, ZERO
from app.indicators import atr, mean, momentum
from app.indicators.technical import true_ranges


class Regime(StrEnum):
    TRENDING_UP = "TRENDING_UP"
    TRENDING_DOWN = "TRENDING_DOWN"
    RANGING = "RANGING"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    LOW_VOLATILITY = "LOW_VOLATILITY"
    RISK_ON = "RISK_ON"
    RISK_OFF = "RISK_OFF"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class RegimeDetectorConfig:
    fast_period: int = 10
    slow_period: int = 30
    atr_period: int = 14
    volatility_lookback: int = 50
    trend_atr_threshold: Decimal = Decimal("0.50")
    high_volatility_ratio: Decimal = Decimal("1.40")
    low_volatility_ratio: Decimal = Decimal("0.70")
    risk_momentum_period: int = 20
    risk_on_threshold: Decimal = Decimal("0.02")


@dataclass(frozen=True, slots=True)
class RegimeResult:
    primary: Regime
    trend: Regime
    volatility: Regime | None
    risk_appetite: Regime | None
    labels: tuple[Regime, ...]
    trend_strength: Decimal
    volatility_ratio: Decimal
    explanation: dict[str, str]


class RegimeDetector:
    def __init__(self, config: RegimeDetectorConfig | None = None) -> None:
        self.config = config or RegimeDetectorConfig()

    @property
    def minimum_bars(self) -> int:
        cfg = self.config
        return (
            max(
                cfg.slow_period,
                cfg.volatility_lookback + cfg.atr_period,
                cfg.risk_momentum_period + 1,
            )
            + 1
        )

    def detect(
        self, bars: Sequence[Bar], *, cross_market_return: Decimal | None = None
    ) -> RegimeResult:
        if len(bars) < self.minimum_bars:
            return RegimeResult(
                Regime.UNKNOWN,
                Regime.UNKNOWN,
                None,
                None,
                (Regime.UNKNOWN,),
                ZERO,
                ONE,
                {"reason": "insufficient completed observations"},
            )
        cfg = self.config
        # Every feature below is a fixed rolling calculation.  Restricting the
        # work to the minimum sufficient suffix is numerically identical and
        # keeps long intraday simulations linear rather than quadratic.
        recent = bars[-self.minimum_bars :]
        closes = [bar.close for bar in recent]
        fast = mean(closes[-cfg.fast_period :])
        slow = mean(closes[-cfg.slow_period :])
        current_atr = atr(recent, cfg.atr_period)
        all_true_ranges = true_ranges(recent)
        baseline_ranges = all_true_ranges[-cfg.volatility_lookback : -cfg.atr_period]
        baseline_atr = mean(baseline_ranges) if baseline_ranges else current_atr
        trend_strength = ZERO if current_atr == ZERO else abs(fast - slow) / current_atr
        if trend_strength < cfg.trend_atr_threshold:
            trend = Regime.RANGING
        elif fast > slow:
            trend = Regime.TRENDING_UP
        else:
            trend = Regime.TRENDING_DOWN

        volatility_ratio = ONE if baseline_atr == ZERO else current_atr / baseline_atr
        volatility: Regime | None = None
        if volatility_ratio >= cfg.high_volatility_ratio:
            volatility = Regime.HIGH_VOLATILITY
        elif volatility_ratio <= cfg.low_volatility_ratio:
            volatility = Regime.LOW_VOLATILITY

        risk_return = cross_market_return
        if risk_return is None:
            risk_return = momentum(closes, cfg.risk_momentum_period)
        risk: Regime | None = None
        if risk_return >= cfg.risk_on_threshold:
            risk = Regime.RISK_ON
        elif risk_return <= -cfg.risk_on_threshold:
            risk = Regime.RISK_OFF

        labels = tuple(item for item in (trend, volatility, risk) if item is not None)
        primary = volatility if volatility is Regime.HIGH_VOLATILITY else trend
        return RegimeResult(
            primary,
            trend,
            volatility,
            risk,
            labels,
            trend_strength,
            volatility_ratio,
            {
                "fast_average": str(fast),
                "slow_average": str(slow),
                "atr": str(current_atr),
                "trend_strength_atr": str(trend_strength),
                "volatility_ratio": str(volatility_ratio),
            },
        )
