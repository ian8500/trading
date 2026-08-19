from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from app.core.decimal import ZERO, as_decimal
from app.risk.models import StrategyHealth


@dataclass(frozen=True, slots=True)
class HealthThresholds:
    minimum_trades: int = 20
    suspend_expectancy_below: Decimal = Decimal("-0.005")
    reduce_expectancy_below: Decimal = ZERO
    suspend_drawdown_above: Decimal = Decimal("0.20")
    observe_cost_burden_above: Decimal = Decimal("0.75")


@dataclass(frozen=True, slots=True)
class StrategyHealthReport:
    state: StrategyHealth
    sample_size: int
    expectancy: Decimal
    win_rate: Decimal
    payoff_ratio: Decimal
    profit_factor: Decimal | None
    maximum_drawdown: Decimal
    cost_burden: Decimal
    reasons: tuple[str, ...]


class StrategyHealthMonitor:
    def __init__(self, thresholds: HealthThresholds | None = None) -> None:
        self.thresholds = thresholds or HealthThresholds()

    def assess(
        self,
        net_returns: Sequence[Decimal],
        *,
        maximum_drawdown: Decimal = ZERO,
        gross_profit: Decimal = ZERO,
        total_cost: Decimal = ZERO,
    ) -> StrategyHealthReport:
        values = tuple(as_decimal(value) for value in net_returns)
        sample = len(values)
        expectancy = sum(values, ZERO) / Decimal(sample) if sample else ZERO
        winners = [value for value in values if value > ZERO]
        losers = [value for value in values if value < ZERO]
        win_rate = Decimal(len(winners)) / Decimal(sample) if sample else ZERO
        average_win = sum(winners, ZERO) / len(winners) if winners else ZERO
        average_loss = abs(sum(losers, ZERO) / len(losers)) if losers else ZERO
        payoff = ZERO if average_loss == ZERO else average_win / average_loss
        profit_factor = None if not losers else sum(winners, ZERO) / abs(sum(losers, ZERO))
        maximum_drawdown = as_decimal(maximum_drawdown)
        gross_profit = as_decimal(gross_profit)
        total_cost = as_decimal(total_cost)
        burden = ZERO if gross_profit <= ZERO else total_cost / gross_profit
        reasons: list[str] = []
        state = StrategyHealth.NORMAL
        if sample < self.thresholds.minimum_trades:
            state = StrategyHealth.OBSERVATION_ONLY
            reasons.append("insufficient observations")
        elif (
            maximum_drawdown >= self.thresholds.suspend_drawdown_above
            or expectancy <= self.thresholds.suspend_expectancy_below
        ):
            state = StrategyHealth.SUSPENDED
            reasons.append("drawdown or expectancy breached suspension threshold")
        elif burden >= self.thresholds.observe_cost_burden_above:
            state = StrategyHealth.OBSERVATION_ONLY
            reasons.append("trading costs consume too much gross profit")
        elif expectancy <= self.thresholds.reduce_expectancy_below:
            state = StrategyHealth.REDUCED_RISK
            reasons.append("rolling expectancy is non-positive")
        return StrategyHealthReport(
            state,
            sample,
            expectancy,
            win_rate,
            payoff,
            profit_factor,
            maximum_drawdown,
            burden,
            tuple(reasons),
        )
