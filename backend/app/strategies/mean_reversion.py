from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from app.backtesting.data_guard import MarketView
from app.core.decimal import ONE, ZERO
from app.indicators import atr, mean, momentum, z_score
from app.opportunities import Direction, OpportunityCandidate
from app.regimes import Regime, RegimeDetector
from app.strategies.base import Strategy


@dataclass(frozen=True, slots=True)
class MeanReversionConfig:
    mean_period: int = 20
    z_entry: Decimal = Decimal("1.75")
    atr_period: int = 14
    atr_stop_multiple: Decimal = Decimal("1.25")
    reward_risk_ratio: Decimal = Decimal("1.5")
    maximum_spread_fraction: Decimal = Decimal("0.003")
    expected_horizon: timedelta = timedelta(hours=8)
    slippage_fraction: Decimal = Decimal("0.0002")
    require_range_regime: bool = True


class MeanReversionStrategy(Strategy):
    def __init__(
        self,
        version_id: str = "mean-reversion-v1",
        config: MeanReversionConfig | None = None,
        regime_detector: RegimeDetector | None = None,
    ) -> None:
        self.version_id = version_id
        self.config = config or MeanReversionConfig()
        self.regime_detector = regime_detector or RegimeDetector()

    def evaluate(self, view: MarketView) -> OpportunityCandidate | None:
        cfg = self.config
        required = max(
            cfg.mean_period,
            cfg.atr_period + 1,
            self.regime_detector.minimum_bars if cfg.require_range_regime else 0,
        )
        visible_count = view.bars.visible_count
        if visible_count < required:
            return None
        bars = view.bars.visible_tail(required)
        latest = bars[-1]
        closes = [bar.close for bar in bars]
        window = closes[-cfg.mean_period :]
        score = z_score(window)
        regime = self.regime_detector.detect(bars)
        if cfg.require_range_regime and regime.trend is not Regime.RANGING:
            return None
        spread_fraction = latest.spread / latest.close
        if spread_fraction > cfg.maximum_spread_fraction:
            return None
        direction: Direction | None = None
        if score <= -cfg.z_entry:
            direction = Direction.LONG
        elif score >= cfg.z_entry:
            direction = Direction.SHORT
        if direction is None:
            return None
        # Require the latest move to be losing momentum rather than accelerating.
        one_bar_momentum = momentum(closes, 1)
        if direction is Direction.LONG and one_bar_momentum < Decimal("-0.03"):
            return None
        if direction is Direction.SHORT and one_bar_momentum > Decimal("0.03"):
            return None
        volatility = atr(bars, cfg.atr_period)
        if volatility <= ZERO:
            return None
        stop_distance = volatility * cfg.atr_stop_multiple
        target_distance = min(
            stop_distance * cfg.reward_risk_ratio,
            abs(latest.close - mean(window)),
        )
        if target_distance <= ZERO:
            return None
        reward_risk = target_distance / stop_distance
        downside = stop_distance / latest.close
        upside = target_distance / latest.close
        raw = min(ONE, abs(score) / Decimal("4"))
        return OpportunityCandidate(
            timestamp=latest.timestamp,
            instrument_id=view.instrument.id,
            strategy_version_id=self.version_id,
            direction=direction,
            signal_price=latest.close,
            expected_horizon=cfg.expected_horizon,
            raw_signal_score=raw,
            calibrated_probability=None,
            expected_upside=upside,
            expected_downside=downside,
            reward_risk_ratio=reward_risk,
            estimated_spread_cost=spread_fraction,
            estimated_slippage=cfg.slippage_fraction,
            estimated_total_cost=spread_fraction + cfg.slippage_fraction,
            volatility=volatility / latest.close,
            liquidity_score=ONE,
            regime=regime.primary.value,
            regime_suitability=ONE if regime.trend is Regime.RANGING else ZERO,
            # Only already completed bars count; no future outcomes or invented
            # probability are used as evidence.
            historical_support=max(0, visible_count - required),
            data_quality=latest.data_quality,
            uncertainty_penalty=Decimal("0.001"),
            proposed_stop_distance=stop_distance,
            proposed_target_distance=target_distance,
            correlation_cluster=view.instrument.correlation_cluster,
            spread_fraction=spread_fraction,
            structured_explanation={
                "signal": "range-regime normalized mean deviation",
                "z_score": str(score),
                "rolling_mean": str(mean(window)),
                "atr": str(volatility),
                "regime_labels": [label.value for label in regime.labels],
            },
        )
