from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.core.decimal import ONE, ZERO, as_decimal


@dataclass(frozen=True, slots=True)
class RiskBand:
    minimum_equity: Decimal
    maximum_equity: Decimal | None
    risk_fraction: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "minimum_equity", as_decimal(self.minimum_equity))
        if self.maximum_equity is not None:
            object.__setattr__(self, "maximum_equity", as_decimal(self.maximum_equity))
        object.__setattr__(self, "risk_fraction", as_decimal(self.risk_fraction))
        if self.minimum_equity < ZERO:
            raise ValueError("minimum_equity cannot be negative")
        if self.maximum_equity is not None and self.maximum_equity <= self.minimum_equity:
            raise ValueError("maximum_equity must be greater than minimum_equity")
        if not ZERO < self.risk_fraction <= ONE:
            raise ValueError("risk_fraction must be in (0, 1]")


class RiskTaper:
    def __init__(self, bands: tuple[RiskBand, ...]) -> None:
        if not bands:
            raise ValueError("at least one risk band is required")
        self.bands = tuple(sorted(bands, key=lambda band: band.minimum_equity))
        for previous, current in zip(self.bands, self.bands[1:], strict=False):
            if previous.maximum_equity is None or current.minimum_equity < previous.maximum_equity:
                raise ValueError("risk taper bands cannot overlap")

    def fraction_for(self, equity: Decimal) -> Decimal:
        equity = as_decimal(equity)
        for band in self.bands:
            if equity >= band.minimum_equity and (
                band.maximum_equity is None or equity < band.maximum_equity
            ):
                return band.risk_fraction
        raise ValueError(f"no risk taper band covers managed equity {equity}")

    @classmethod
    def research_default(cls) -> RiskTaper:
        return cls(
            (
                RiskBand(Decimal("0"), Decimal("1000"), Decimal("0.04")),
                RiskBand(Decimal("1000"), Decimal("2500"), Decimal("0.03")),
                RiskBand(Decimal("2500"), Decimal("4000"), Decimal("0.02")),
                RiskBand(Decimal("4000"), None, Decimal("0.01")),
            )
        )


def resolve_risk_taper(value: RiskTaper | bool | None) -> RiskTaper | None:
    if value is True:
        return RiskTaper.research_default()
    if value is False or value is None:
        return None
    if isinstance(value, RiskTaper):
        return value
    raise TypeError("risk_taper must be a RiskTaper or boolean")
