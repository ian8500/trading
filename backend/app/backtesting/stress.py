from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from app.core.decimal import ONE, ZERO, as_decimal


@dataclass(frozen=True, slots=True)
class StressScenario:
    name: str
    extra_cost_per_trade: Decimal = ZERO
    winner_multiplier: Decimal = ONE
    loser_multiplier: Decimal = ONE
    forced_gap_loss: Decimal = ZERO
    missing_trade_probability: Decimal = ZERO
    execution_delay_penalty: Decimal = ZERO

    def __post_init__(self) -> None:
        for name in (
            "extra_cost_per_trade",
            "winner_multiplier",
            "loser_multiplier",
            "forced_gap_loss",
            "missing_trade_probability",
            "execution_delay_penalty",
        ):
            object.__setattr__(self, name, as_decimal(getattr(self, name)))


def apply_stress(
    returns: Sequence[Decimal],
    scenario: StressScenario,
    *,
    seed: int = 0,
) -> tuple[Decimal, ...]:
    import random

    random_source = random.Random(seed)  # noqa: S311 - reproducible research, not security
    stressed: list[Decimal] = []
    for value in returns:
        value = as_decimal(value)
        if random_source.random() < float(scenario.missing_trade_probability):
            continue
        adjusted = (
            value * scenario.winner_multiplier
            if value >= ZERO
            else value * scenario.loser_multiplier
        )
        adjusted -= scenario.extra_cost_per_trade + scenario.execution_delay_penalty
        stressed.append(adjusted)
    if scenario.forced_gap_loss > ZERO:
        stressed.append(-scenario.forced_gap_loss)
    return tuple(stressed)


STANDARD_STRESS_SCENARIOS = (
    StressScenario("wider_spread", extra_cost_per_trade=Decimal("0.001")),
    StressScenario("increased_slippage", extra_cost_per_trade=Decimal("0.002")),
    StressScenario("execution_delay", execution_delay_penalty=Decimal("0.001")),
    StressScenario("reduced_win_rate", missing_trade_probability=Decimal("0.10")),
    StressScenario("smaller_winners", winner_multiplier=Decimal("0.75")),
    StressScenario("larger_losers", loser_multiplier=Decimal("1.25")),
    StressScenario("market_gap", forced_gap_loss=Decimal("0.10")),
    StressScenario("higher_funding", extra_cost_per_trade=Decimal("0.0005")),
)
