from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal, localcontext
from itertools import pairwise

from app.backtesting.models import Bar
from app.core.decimal import ZERO, as_decimal


def mean(values: Sequence[Decimal]) -> Decimal:
    if not values:
        raise ValueError("values cannot be empty")
    return sum((as_decimal(v) for v in values), ZERO) / Decimal(len(values))


def standard_deviation(values: Sequence[Decimal]) -> Decimal:
    if len(values) < 2:
        return ZERO
    centre = mean(values)
    variance = sum(((as_decimal(v) - centre) ** 2 for v in values), ZERO) / Decimal(len(values))
    with localcontext() as ctx:
        ctx.prec = 28
        return variance.sqrt()


def momentum(values: Sequence[Decimal], period: int) -> Decimal:
    if period <= 0 or len(values) <= period:
        raise ValueError("insufficient observations for momentum period")
    previous = as_decimal(values[-period - 1])
    return ZERO if previous == ZERO else as_decimal(values[-1]) / previous - Decimal("1")


def true_ranges(bars: Sequence[Bar]) -> tuple[Decimal, ...]:
    if not bars:
        return ()
    ranges: list[Decimal] = [bars[0].high - bars[0].low]
    for previous, current in pairwise(bars):
        ranges.append(
            max(
                current.high - current.low,
                abs(current.high - previous.close),
                abs(current.low - previous.close),
            )
        )
    return tuple(ranges)


def atr(bars: Sequence[Bar], period: int = 14) -> Decimal:
    if period <= 0 or len(bars) < period + 1:
        raise ValueError("insufficient bars for ATR")
    return mean(true_ranges(bars)[-period:])


def z_score(values: Sequence[Decimal]) -> Decimal:
    deviation = standard_deviation(values)
    return ZERO if deviation == ZERO else (as_decimal(values[-1]) - mean(values)) / deviation
