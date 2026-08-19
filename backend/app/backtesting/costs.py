from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from app.backtesting.models import Bar, Position
from app.core.decimal import ZERO, as_decimal, money
from app.instruments import Instrument


class CostPreset(StrEnum):
    ZERO = "ZERO"
    OPTIMISTIC = "OPTIMISTIC"
    REALISTIC = "REALISTIC"
    STRESSED = "STRESSED"


@dataclass(frozen=True, slots=True)
class CostModel:
    preset: CostPreset = CostPreset.REALISTIC
    spread_bps: Decimal = Decimal("2.0")
    slippage_bps_per_side: Decimal = Decimal("0.5")
    commission_bps_per_side: Decimal = Decimal("0.25")
    financing_bps_per_day: Decimal = Decimal("0.5")
    guaranteed_stop_premium_bps: Decimal = ZERO
    currency_conversion_bps: Decimal = ZERO

    def __post_init__(self) -> None:
        object.__setattr__(self, "preset", CostPreset(self.preset))
        for name in (
            "spread_bps",
            "slippage_bps_per_side",
            "commission_bps_per_side",
            "financing_bps_per_day",
            "guaranteed_stop_premium_bps",
            "currency_conversion_bps",
        ):
            value = as_decimal(getattr(self, name))
            if value < ZERO:
                raise ValueError(f"{name} cannot be negative")
            object.__setattr__(self, name, value)

    @classmethod
    def from_preset(cls, preset: CostPreset | str) -> CostModel:
        preset = CostPreset(preset)
        values = {
            CostPreset.ZERO: dict(
                spread_bps=ZERO,
                slippage_bps_per_side=ZERO,
                commission_bps_per_side=ZERO,
                financing_bps_per_day=ZERO,
            ),
            CostPreset.OPTIMISTIC: dict(
                spread_bps=Decimal("1"),
                slippage_bps_per_side=Decimal("0.1"),
                commission_bps_per_side=Decimal("0.1"),
                financing_bps_per_day=Decimal("0.2"),
            ),
            CostPreset.REALISTIC: dict(
                spread_bps=Decimal("2"),
                slippage_bps_per_side=Decimal("0.5"),
                commission_bps_per_side=Decimal("0.25"),
                financing_bps_per_day=Decimal("0.5"),
            ),
            CostPreset.STRESSED: dict(
                spread_bps=Decimal("5"),
                slippage_bps_per_side=Decimal("2"),
                commission_bps_per_side=Decimal("0.5"),
                financing_bps_per_day=Decimal("1.5"),
            ),
        }
        return cls(preset=preset, **values[preset])

    def half_spread_price(self, bar: Bar, price: Decimal) -> Decimal:
        if bar.spread > ZERO:
            return bar.spread / Decimal("2")
        return price * self.spread_bps / Decimal("20000")

    def slippage_price(self, price: Decimal) -> Decimal:
        return price * self.slippage_bps_per_side / Decimal("10000")


@dataclass(frozen=True, slots=True)
class ExitCosts:
    spread: Decimal
    slippage: Decimal
    financing: Decimal
    commission: Decimal
    guaranteed_stop_premium: Decimal
    currency_conversion: Decimal

    @property
    def total(self) -> Decimal:
        return money(
            self.spread
            + self.slippage
            + self.financing
            + self.commission
            + self.guaranteed_stop_premium
            + self.currency_conversion
        )


def monetary_price_distance(
    distance: Decimal,
    size: Decimal,
    instrument: Instrument,
) -> Decimal:
    return money(
        abs(distance)
        * size
        * instrument.point_value
        * instrument.contract_size
        * instrument.currency_conversion
    )


def calculate_exit_costs(
    model: CostModel,
    position: Position,
    exit_bar: Bar,
    requested_exit: Decimal,
    instrument: Instrument,
    holding_seconds: int,
) -> ExitCosts:
    exit_half_spread = model.half_spread_price(exit_bar, requested_exit)
    exit_slippage = model.slippage_price(requested_exit)
    spread = position.entry_spread_cost + monetary_price_distance(
        exit_half_spread, position.quantity, instrument
    )
    slippage = position.entry_slippage_cost + monetary_price_distance(
        exit_slippage, position.quantity, instrument
    )
    entry_notional = (
        position.requested_entry
        * position.quantity
        * instrument.contract_size
        * instrument.currency_conversion
    )
    exit_notional = (
        requested_exit
        * position.quantity
        * instrument.contract_size
        * instrument.currency_conversion
    )
    commission = money(
        (entry_notional + exit_notional) * model.commission_bps_per_side / Decimal("10000")
    )
    holding_days = Decimal(max(0, holding_seconds)) / Decimal("86400")
    financing = money(
        entry_notional * model.financing_bps_per_day / Decimal("10000") * holding_days
    )
    premium = money(entry_notional * model.guaranteed_stop_premium_bps / Decimal("10000"))
    conversion = money(
        abs(exit_notional - entry_notional) * model.currency_conversion_bps / Decimal("10000")
    )
    return ExitCosts(spread, slippage, financing, commission, premium, conversion)
