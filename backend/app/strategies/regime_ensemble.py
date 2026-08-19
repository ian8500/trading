from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal

from app.backtesting.data_guard import MarketView
from app.opportunities import OpportunityCandidate
from app.regimes import Regime, RegimeDetector
from app.strategies.base import Strategy
from app.strategies.mean_reversion import MeanReversionStrategy
from app.strategies.trend_breakout import TrendBreakoutStrategy


@dataclass(frozen=True, slots=True)
class RegimeEnsembleConfig:
    high_volatility_no_trade: bool = True
    trend_weight: Decimal = Decimal("1.0")
    range_weight: Decimal = Decimal("1.0")


class RegimeEnsembleStrategy(Strategy):
    def __init__(
        self,
        version_id: str = "regime-ensemble-v1",
        *,
        trend_strategy: TrendBreakoutStrategy | None = None,
        mean_reversion_strategy: MeanReversionStrategy | None = None,
        regime_detector: RegimeDetector | None = None,
        config: RegimeEnsembleConfig | None = None,
    ) -> None:
        self.version_id = version_id
        self.regime_detector = regime_detector or RegimeDetector()
        self.trend_strategy = trend_strategy or TrendBreakoutStrategy(
            regime_detector=self.regime_detector
        )
        self.mean_reversion_strategy = mean_reversion_strategy or MeanReversionStrategy(
            regime_detector=self.regime_detector
        )
        self.config = config or RegimeEnsembleConfig()

    def evaluate(self, view: MarketView) -> OpportunityCandidate | None:
        bars = view.bars.visible_tail(self.regime_detector.minimum_bars)
        regime = self.regime_detector.detect(bars)
        if regime.primary is Regime.UNKNOWN:
            return None
        if self.config.high_volatility_no_trade and regime.volatility is Regime.HIGH_VOLATILITY:
            return None
        if regime.trend in (Regime.TRENDING_UP, Regime.TRENDING_DOWN):
            child = self.trend_strategy.evaluate(view)
            weight = self.config.trend_weight
            selected = "trend_breakout"
        elif regime.trend is Regime.RANGING:
            child = self.mean_reversion_strategy.evaluate(view)
            weight = self.config.range_weight
            selected = "mean_reversion"
        else:
            return None
        if child is None:
            return None
        explanation = dict(child.structured_explanation)
        explanation.update(
            {
                "ensemble_selected": selected,
                "ensemble_weight": str(weight),
                "ensemble_regime": regime.primary.value,
            }
        )
        return replace(
            child,
            strategy_version_id=self.version_id,
            raw_signal_score=min(Decimal("1"), child.raw_signal_score * weight),
            structured_explanation=explanation,
        )
