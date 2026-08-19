from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from app.backtesting.data_guard import MarketView
from app.core.decimal import ONE, ZERO
from app.indicators import atr, mean, momentum
from app.opportunities import Direction, OpportunityCandidate
from app.regimes import Regime, RegimeDetector
from app.strategies.base import Strategy


@dataclass(frozen=True, slots=True)
class TrendBreakoutConfig:
    fast_period: int = 10
    slow_period: int = 30
    momentum_period: int = 10
    breakout_period: int = 20
    atr_period: int = 14
    atr_stop_multiple: Decimal = Decimal("1.5")
    reward_risk_ratio: Decimal = Decimal("2.0")
    maximum_extension_atr: Decimal = Decimal("3.0")
    maximum_spread_fraction: Decimal = Decimal("0.003")
    expected_horizon: timedelta = timedelta(hours=12)
    slippage_fraction: Decimal = Decimal("0.0002")
    minimum_raw_score: Decimal = Decimal("0.10")
    require_regime_match: bool = True


class TrendBreakoutStrategy(Strategy):
    def __init__(
        self,
        version_id: str = "trend-breakout-v1",
        config: TrendBreakoutConfig | None = None,
        regime_detector: RegimeDetector | None = None,
    ) -> None:
        self.version_id = version_id
        self.config = config or TrendBreakoutConfig()
        self.regime_detector = regime_detector or RegimeDetector()

    def evaluate(self, view: MarketView) -> OpportunityCandidate | None:
        cfg = self.config
        required = max(
            cfg.slow_period,
            cfg.momentum_period + 1,
            cfg.breakout_period + 1,
            cfg.atr_period + 1,
            self.regime_detector.minimum_bars if cfg.require_regime_match else 0,
        )
        visible_count = view.bars.visible_count
        if visible_count < required:
            return None
        bars = view.bars.visible_tail(required)
        closes = [bar.close for bar in bars]
        latest = bars[-1]
        fast = mean(closes[-cfg.fast_period :])
        slow = mean(closes[-cfg.slow_period :])
        momentum_value = momentum(closes, cfg.momentum_period)
        volatility = atr(bars, cfg.atr_period)
        if volatility <= ZERO:
            return None
        spread_fraction = latest.spread / latest.close
        if spread_fraction > cfg.maximum_spread_fraction:
            return None
        prior = bars[-cfg.breakout_period - 1 : -1]
        previous_high = max(bar.high for bar in prior)
        previous_low = min(bar.low for bar in prior)
        regime = self.regime_detector.detect(bars)
        extension = abs(latest.close - slow) / volatility
        if extension > cfg.maximum_extension_atr:
            return None

        direction: Direction | None = None
        suitable = ONE
        if fast > slow and momentum_value > ZERO and latest.close > previous_high:
            direction = Direction.LONG
            suitable = ONE if regime.trend is Regime.TRENDING_UP else Decimal("0.40")
        elif fast < slow and momentum_value < ZERO and latest.close < previous_low:
            direction = Direction.SHORT
            suitable = ONE if regime.trend is Regime.TRENDING_DOWN else Decimal("0.40")
        if direction is None:
            return None
        if cfg.require_regime_match and suitable < ONE:
            return None

        breakout_distance = (
            latest.close - previous_high
            if direction is Direction.LONG
            else previous_low - latest.close
        )
        raw = min(
            ONE,
            max(ZERO, abs(momentum_value) * Decimal("8") + breakout_distance / volatility),
        )
        if raw < cfg.minimum_raw_score:
            return None
        stop_distance = volatility * cfg.atr_stop_multiple
        target_distance = stop_distance * cfg.reward_risk_ratio
        downside = stop_distance / latest.close
        upside = target_distance / latest.close
        estimated_total = spread_fraction + cfg.slippage_fraction
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
            reward_risk_ratio=cfg.reward_risk_ratio,
            estimated_spread_cost=spread_fraction,
            estimated_slippage=cfg.slippage_fraction,
            estimated_total_cost=estimated_total,
            volatility=volatility / latest.close,
            liquidity_score=ONE,
            regime=regime.primary.value,
            regime_suitability=suitable,
            # Causal support count: completed observations available beyond the
            # minimum feature warm-up.  This is not presented as calibrated
            # win evidence, so probability deliberately remains None.
            historical_support=max(0, visible_count - required),
            data_quality=latest.data_quality,
            uncertainty_penalty=Decimal("0.001"),
            proposed_stop_distance=stop_distance,
            proposed_target_distance=target_distance,
            correlation_cluster=view.instrument.correlation_cluster,
            spread_fraction=spread_fraction,
            structured_explanation={
                "signal": "trend and completed-bar breakout agree",
                "fast_average": str(fast),
                "slow_average": str(slow),
                "momentum": str(momentum_value),
                "breakout_reference": str(
                    previous_high if direction is Direction.LONG else previous_low
                ),
                "atr": str(volatility),
                "regime_labels": [label.value for label in regime.labels],
            },
        )
