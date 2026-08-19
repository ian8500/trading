"""Provider-neutral broker contracts.

The strategy and risk layers should depend on these deliberately small value
objects instead of importing provider-specific response shapes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, cast


class BrokerEnvironment(StrEnum):
    SIMULATED = "SIMULATED"
    IG_DEMO = "IG_DEMO"
    IG_LIVE = "IG_LIVE"


class Direction(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class BrokerOrderStatus(StrEnum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    AMBIGUOUS = "AMBIGUOUS"


@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    account_id: str = field(repr=False)
    account_name: str
    currency: str
    balance: Decimal
    available: Decimal
    profit_loss: Decimal
    preferred: bool = False
    status: str | None = None


@dataclass(frozen=True, slots=True)
class PriceQuote:
    epic: str
    bid: Decimal
    ask: Decimal
    timestamp: datetime
    market_status: str
    delayed: bool = False
    source: str = "broker"

    @property
    def midpoint(self) -> Decimal:
        return (self.bid + self.ask) / Decimal("2")

    @property
    def spread(self) -> Decimal:
        return self.ask - self.bid


@dataclass(frozen=True, slots=True)
class HistoricalBar:
    epic: str
    timestamp: datetime
    open_bid: Decimal | None
    open_ask: Decimal | None
    high_bid: Decimal | None
    high_ask: Decimal | None
    low_bid: Decimal | None
    low_ask: Decimal | None
    close_bid: Decimal | None
    close_ask: Decimal | None
    volume: Decimal | None = None


@dataclass(frozen=True, slots=True)
class MarketCapability:
    epic: str
    instrument_name: str
    instrument_type: str
    currency: str | None
    market_status: str
    opening_hours: tuple[Mapping[str, Any], ...]
    tradeable: bool
    market_order_supported: bool | None
    force_open_supported: bool | None
    stops_limits_supported: bool | None
    snapshot_pricing_supported: bool
    streaming_pricing_supported: bool
    historical_pricing_supported: bool | None
    minimum_deal_size: Decimal | None
    maximum_deal_size: Decimal | None
    contract_size: Decimal | None
    value_of_one_pip: Decimal | None
    margin_factor: Decimal | None
    controlled_risk_supported: bool
    guaranteed_stop_supported: bool
    minimum_stop_distance: Decimal | None
    minimum_guaranteed_stop_distance: Decimal | None
    minimum_limit_distance: Decimal | None
    expiry: str | None
    rolling: bool
    overnight_funding_applicable: bool | None
    raw_rule_units: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class BrokerPosition:
    deal_id: str
    deal_reference: str | None
    epic: str
    direction: Direction
    size: Decimal
    level: Decimal
    currency: str | None
    stop_level: Decimal | None
    limit_level: Decimal | None
    controlled_risk: bool
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class BrokerOrderResult:
    intent_id: str
    status: BrokerOrderStatus
    deal_reference: str | None = None
    deal_id: str | None = None
    reason: str | None = None
    raw_confirmation: Mapping[str, Any] | None = field(default=None, repr=False)


class Broker(ABC):
    """Asynchronous interface implemented by real and simulated brokers."""

    environment: BrokerEnvironment

    @abstractmethod
    async def connect(self) -> None:
        """Authenticate and initialise the broker session."""

    @abstractmethod
    async def close(self) -> None:
        """Close sessions and streams without opening or closing trades."""

    @abstractmethod
    async def accounts(self) -> Sequence[AccountSnapshot]:
        """Return broker balances, which are informational to managed capital."""

    @abstractmethod
    async def market_capability(self, epic: str) -> MarketCapability:
        """Discover provider capabilities for one instrument."""

    @abstractmethod
    async def quote(self, epic: str) -> PriceQuote:
        """Return a current price snapshot."""

    @abstractmethod
    async def positions(self) -> Sequence[BrokerPosition]:
        """Return all open positions for the selected account."""

    async def stream_quotes(self, epics: Sequence[str]) -> AsyncIterator[PriceQuote]:
        """Optional streaming interface.

        Implementations without an installed streaming adapter should raise a
        provider-specific configuration error instead of silently polling.
        """

        del epics
        if False:  # pragma: no cover - makes this an async generator contract
            yield cast(PriceQuote, None)
        raise NotImplementedError
