from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from app.core.decimal import ONE, ZERO, as_decimal, money

TARGETS = (Decimal("750"), Decimal("1000"), Decimal("2500"), Decimal("5000"))


@dataclass(frozen=True, slots=True)
class MonteCarloResult:
    simulations: int
    seed: int
    median_final_equity: Decimal
    percentile_5: Decimal
    percentile_25: Decimal
    percentile_75: Decimal
    percentile_95: Decimal
    probability_below_start: Decimal
    probability_losing_25_percent: Decimal
    probability_losing_50_percent: Decimal
    probability_of_ruin: Decimal
    target_probabilities: dict[str, Decimal]
    drawdown_percentiles: dict[str, Decimal]
    median_time_to_target: dict[str, int | None]
    final_equities: tuple[Decimal, ...]


def _percentile(values: Sequence[Decimal], percentile: Decimal) -> Decimal:
    if not values:
        raise ValueError("percentile requires observations")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = percentile * Decimal(len(ordered) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - Decimal(lower)
    return ordered[lower] * (ONE - weight) + ordered[upper] * weight


class TradeSequenceMonteCarlo:
    """Seeded bootstrap or permutation analysis over net trade-return fractions."""

    def run(
        self,
        trade_returns: Sequence[Decimal],
        *,
        starting_equity: Decimal = Decimal("500"),
        simulations: int = 1000,
        seed: int = 0,
        bootstrap: bool = True,
    ) -> MonteCarloResult:
        returns = tuple(as_decimal(value) for value in trade_returns)
        if not returns:
            raise ValueError("trade_returns cannot be empty")
        if simulations <= 0:
            raise ValueError("simulations must be positive")
        starting = money(starting_equity)
        random_source = random.Random(seed)  # noqa: S311 - reproducible research, not security
        finals: list[Decimal] = []
        drawdowns: list[Decimal] = []
        target_hits: dict[Decimal, int] = {target: 0 for target in TARGETS}
        target_times: dict[Decimal, list[int]] = {target: [] for target in TARGETS}
        ruin_count = 0
        for _ in range(simulations):
            if bootstrap:
                sequence = [random_source.choice(returns) for _ in returns]
            else:
                sequence = list(returns)
                random_source.shuffle(sequence)
            equity = starting
            peak = starting
            max_drawdown = ZERO
            first_hits: dict[Decimal, int] = {}
            ruined = False
            for trade_number, trade_return in enumerate(sequence, 1):
                equity = money(equity * (ONE + trade_return))
                if equity <= ZERO:
                    equity = ZERO
                    ruined = True
                peak = max(peak, equity)
                if peak > ZERO:
                    max_drawdown = max(max_drawdown, (peak - equity) / peak)
                for target in TARGETS:
                    if target not in first_hits and equity >= target:
                        first_hits[target] = trade_number
                if ruined:
                    break
            finals.append(equity)
            drawdowns.append(max_drawdown)
            ruin_count += ruined
            for target, trade_number in first_hits.items():
                target_hits[target] += 1
                target_times[target].append(trade_number)
        denominator = Decimal(simulations)
        median_times: dict[str, int | None] = {}
        for target, values in target_times.items():
            values.sort()
            median_times[str(target)] = values[len(values) // 2] if values else None
        return MonteCarloResult(
            simulations=simulations,
            seed=seed,
            median_final_equity=money(_percentile(finals, Decimal("0.50"))),
            percentile_5=money(_percentile(finals, Decimal("0.05"))),
            percentile_25=money(_percentile(finals, Decimal("0.25"))),
            percentile_75=money(_percentile(finals, Decimal("0.75"))),
            percentile_95=money(_percentile(finals, Decimal("0.95"))),
            probability_below_start=Decimal(sum(value < starting for value in finals))
            / denominator,
            probability_losing_25_percent=Decimal(
                sum(value <= starting * Decimal("0.75") for value in finals)
            )
            / denominator,
            probability_losing_50_percent=Decimal(
                sum(value <= starting * Decimal("0.50") for value in finals)
            )
            / denominator,
            probability_of_ruin=Decimal(ruin_count) / denominator,
            target_probabilities={
                str(target): Decimal(count) / denominator for target, count in target_hits.items()
            },
            drawdown_percentiles={
                "5": _percentile(drawdowns, Decimal("0.05")),
                "25": _percentile(drawdowns, Decimal("0.25")),
                "50": _percentile(drawdowns, Decimal("0.50")),
                "75": _percentile(drawdowns, Decimal("0.75")),
                "95": _percentile(drawdowns, Decimal("0.95")),
            },
            median_time_to_target=median_times,
            final_equities=tuple(finals),
        )
