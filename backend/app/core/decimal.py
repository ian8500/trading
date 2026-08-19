"""Decimal helpers.

Money is deliberately kept out of binary floating point.  Indicators may use
floats, but values that can change account equity pass through these helpers.
"""

from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

type DecimalLike = Decimal | int | str | float

ZERO = Decimal("0")
ONE = Decimal("1")
MONEY_QUANTUM = Decimal("0.01")
QUANTITY_QUANTUM = Decimal("0.00000001")


def as_decimal(value: DecimalLike) -> Decimal:
    """Convert without importing binary-float artefacts into account values."""

    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(str(value))
    return Decimal(value)


def money(value: DecimalLike, currency_quantum: Decimal = MONEY_QUANTUM) -> Decimal:
    return as_decimal(value).quantize(currency_quantum, rounding=ROUND_HALF_UP)


def quantity(value: DecimalLike, quantum: Decimal = QUANTITY_QUANTUM) -> Decimal:
    return as_decimal(value).quantize(quantum, rounding=ROUND_DOWN)


def floor_to_step(value: DecimalLike, step: DecimalLike) -> Decimal:
    value_d = as_decimal(value)
    step_d = as_decimal(step)
    if step_d <= ZERO:
        raise ValueError("step must be positive")
    return (value_d / step_d).to_integral_value(rounding=ROUND_DOWN) * step_d


def safe_ratio(numerator: DecimalLike, denominator: DecimalLike) -> Decimal:
    denominator_d = as_decimal(denominator)
    return ZERO if denominator_d == ZERO else as_decimal(numerator) / denominator_d
