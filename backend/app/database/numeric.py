"""Canonical numeric storage precision shared by every database backend."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

PRICE_QUANTUM = Decimal("0.0000000001")
VOLUME_QUANTUM = Decimal("0.00000001")
DATA_QUALITY_QUANTUM = Decimal("0.000001")


def quantize_price(value: Decimal) -> Decimal:
    """Match the declared ``NUMERIC(24, 10)`` persistence contract."""
    return value.quantize(PRICE_QUANTUM, rounding=ROUND_HALF_UP)


def quantize_volume(value: Decimal) -> Decimal:
    """Match the declared ``NUMERIC(30, 8)`` persistence contract."""
    return value.quantize(VOLUME_QUANTUM, rounding=ROUND_HALF_UP)


def quantize_data_quality(value: Decimal) -> Decimal:
    """Match the declared ``NUMERIC(8, 6)`` persistence contract."""
    return value.quantize(DATA_QUALITY_QUANTUM, rounding=ROUND_HALF_UP)
