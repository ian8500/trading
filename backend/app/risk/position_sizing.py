from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.core.decimal import ZERO, as_decimal, floor_to_step, money, quantity
from app.instruments import Instrument


@dataclass(frozen=True, slots=True)
class PositionSizingRequest:
    equity: Decimal
    risk_fraction: Decimal
    entry_price: Decimal
    stop_distance: Decimal
    instrument: Instrument
    expected_cost_per_unit: Decimal = ZERO
    expected_gap_per_unit: Decimal = ZERO
    available_margin: Decimal | None = None

    def __post_init__(self) -> None:
        for name in (
            "equity",
            "risk_fraction",
            "entry_price",
            "stop_distance",
            "expected_cost_per_unit",
            "expected_gap_per_unit",
        ):
            object.__setattr__(self, name, as_decimal(getattr(self, name)))
        if self.available_margin is not None:
            object.__setattr__(self, "available_margin", as_decimal(self.available_margin))


@dataclass(frozen=True, slots=True)
class PositionSizingResult:
    accepted: bool
    size: Decimal
    permitted_risk: Decimal
    actual_risk: Decimal
    loss_per_unit: Decimal
    notional: Decimal
    margin_required: Decimal
    reason: str | None = None


class PositionSizer:
    def calculate(self, request: PositionSizingRequest) -> PositionSizingResult:
        instrument = request.instrument
        if request.equity <= ZERO:
            return self._rejected("managed equity is exhausted")
        if not ZERO < request.risk_fraction <= Decimal("1"):
            return self._rejected("risk fraction must be in (0, 1]")
        if request.entry_price <= ZERO or request.stop_distance <= ZERO:
            return self._rejected("entry price and stop distance must be positive")
        if request.stop_distance < instrument.min_stop_distance:
            return self._rejected("stop distance is below instrument minimum")

        permitted = money(request.equity * request.risk_fraction)
        price_loss = (
            request.stop_distance
            * instrument.point_value
            * instrument.contract_size
            * instrument.currency_conversion
        )
        loss_per_unit = price_loss + request.expected_cost_per_unit + request.expected_gap_per_unit
        if loss_per_unit <= ZERO:
            return self._rejected("monetary loss at stop must be positive")
        raw_size = permitted / loss_per_unit
        size = floor_to_step(raw_size, instrument.size_step)
        if instrument.max_deal_size is not None:
            size = min(size, instrument.max_deal_size)
        if size < instrument.min_deal_size:
            minimum_risk = money(instrument.min_deal_size * loss_per_unit)
            return PositionSizingResult(
                accepted=False,
                size=ZERO,
                permitted_risk=permitted,
                actual_risk=minimum_risk,
                loss_per_unit=loss_per_unit,
                notional=ZERO,
                margin_required=ZERO,
                reason="minimum deal size exceeds permitted monetary risk",
            )

        size = quantity(size, instrument.size_step)
        actual_risk = money(size * loss_per_unit)
        notional = money(
            request.entry_price * size * instrument.contract_size * instrument.currency_conversion
        )
        margin = money(notional * instrument.margin_factor)
        if request.available_margin is not None and margin > request.available_margin:
            return PositionSizingResult(
                accepted=False,
                size=ZERO,
                permitted_risk=permitted,
                actual_risk=actual_risk,
                loss_per_unit=loss_per_unit,
                notional=notional,
                margin_required=margin,
                reason="insufficient available margin",
            )
        return PositionSizingResult(
            accepted=True,
            size=size,
            permitted_risk=permitted,
            actual_risk=actual_risk,
            loss_per_unit=loss_per_unit,
            notional=notional,
            margin_required=margin,
        )

    @staticmethod
    def _rejected(reason: str) -> PositionSizingResult:
        return PositionSizingResult(False, ZERO, ZERO, ZERO, ZERO, ZERO, ZERO, reason)
