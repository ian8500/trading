from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from app.core.decimal import ONE, ZERO, as_decimal


class AssetClass(StrEnum):
    FX = "FX"
    INDEX = "INDEX"
    COMMODITY = "COMMODITY"
    CRYPTO = "CRYPTO"
    EQUITY = "EQUITY"


class InstrumentDefinitionLike(Protocol):
    symbol: str
    name: str
    asset_class: str
    currency: str
    point_value: Decimal
    minimum_size: Decimal
    margin_factor: Decimal
    contract_size: Decimal
    size_step: Decimal
    economics_version: str
    economics_provenance: str


@dataclass(frozen=True, slots=True)
class Instrument:
    """Provider-independent trading and sizing metadata."""

    id: str
    name: str
    asset_class: AssetClass
    quote_currency: str = "GBP"
    point_value: Decimal = ONE
    contract_size: Decimal = ONE
    min_deal_size: Decimal = Decimal("0.01")
    size_step: Decimal = Decimal("0.01")
    max_deal_size: Decimal | None = None
    margin_factor: Decimal = Decimal("0.05")
    currency_conversion: Decimal = ONE
    tradeable: bool = True
    market_open: bool = True
    historical_supported: bool = True
    min_stop_distance: Decimal = ZERO
    min_limit_distance: Decimal = ZERO
    correlation_cluster: str | None = None
    exposure_tags: frozenset[str] = field(default_factory=frozenset)
    economics_version: str = "generic-instrument-v1"
    economics_provenance: str = "Caller-supplied instrument economics."

    def __post_init__(self) -> None:
        decimal_fields = (
            "point_value",
            "contract_size",
            "min_deal_size",
            "size_step",
            "margin_factor",
            "currency_conversion",
            "min_stop_distance",
            "min_limit_distance",
        )
        for field_name in decimal_fields:
            object.__setattr__(self, field_name, as_decimal(getattr(self, field_name)))
        if self.max_deal_size is not None:
            object.__setattr__(self, "max_deal_size", as_decimal(self.max_deal_size))
        if self.point_value <= ZERO or self.contract_size <= ZERO:
            raise ValueError("point_value and contract_size must be positive")
        if self.min_deal_size <= ZERO or self.size_step <= ZERO:
            raise ValueError("deal sizes must be positive")
        if not self.currency_conversion > ZERO:
            raise ValueError("currency_conversion must be positive")
        if not ZERO <= self.margin_factor <= ONE:
            raise ValueError("margin_factor must be between zero and one")

    @classmethod
    def from_definition(cls, definition: InstrumentDefinitionLike) -> Instrument:
        """Adapt a provider definition without coupling the domain to its module."""

        raw_asset_class = str(definition.asset_class)
        return cls(
            id=str(definition.symbol),
            name=str(definition.name),
            asset_class=AssetClass(raw_asset_class),
            quote_currency=str(getattr(definition, "currency", "GBP")),
            point_value=as_decimal(getattr(definition, "point_value", ONE)),
            contract_size=as_decimal(getattr(definition, "contract_size", ONE)),
            min_deal_size=as_decimal(getattr(definition, "minimum_size", Decimal("0.01"))),
            size_step=as_decimal(getattr(definition, "size_step", Decimal("0.01"))),
            margin_factor=as_decimal(getattr(definition, "margin_factor", Decimal("0.05"))),
            economics_version=str(
                getattr(definition, "economics_version", "research-contract-proxy-v1")
            ),
            economics_provenance=str(
                getattr(
                    definition,
                    "economics_provenance",
                    "Versioned research contract proxy only; not an IG product specification.",
                )
            ),
        )
