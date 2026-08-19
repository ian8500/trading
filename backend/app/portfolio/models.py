from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from app.core.decimal import ZERO, as_decimal
from app.opportunities import Direction


@dataclass(frozen=True, slots=True)
class OpenExposure:
    instrument_id: str
    direction: Direction
    monetary_risk: Decimal
    notional: Decimal
    margin: Decimal
    correlation_cluster: str | None = None
    strategy_version_id: str = ""
    exposure_tags: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        object.__setattr__(self, "direction", Direction(self.direction))
        for name in ("monetary_risk", "notional", "margin"):
            object.__setattr__(self, name, as_decimal(getattr(self, name)))


@dataclass(frozen=True, slots=True)
class PortfolioRiskState:
    positions: tuple[OpenExposure, ...] = ()
    daily_loss: Decimal = ZERO
    weekly_loss: Decimal = ZERO
    peak_equity: Decimal | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "daily_loss", as_decimal(self.daily_loss))
        object.__setattr__(self, "weekly_loss", as_decimal(self.weekly_loss))
        if self.peak_equity is not None:
            object.__setattr__(self, "peak_equity", as_decimal(self.peak_equity))

    @property
    def open_risk(self) -> Decimal:
        return sum((p.monetary_risk for p in self.positions), ZERO)

    @property
    def gross_notional(self) -> Decimal:
        return sum((p.notional for p in self.positions), ZERO)

    @property
    def margin_used(self) -> Decimal:
        return sum((p.margin for p in self.positions), ZERO)

    def correlation_risk(self, cluster: str | None, direction: Direction) -> Decimal:
        if not cluster:
            return ZERO
        return sum(
            (
                p.monetary_risk
                for p in self.positions
                if p.correlation_cluster == cluster and p.direction is direction
            ),
            ZERO,
        )
