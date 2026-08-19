from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol

from app.core.clock import ensure_utc
from app.core.decimal import ZERO, as_decimal
from app.opportunities import Direction


class HistoricalBarLike(Protocol):
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    complete: bool


@dataclass(frozen=True, slots=True)
class Bar:
    """A completed OHLCV bar; ``timestamp`` is its completion time."""

    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal = ZERO
    spread: Decimal = ZERO
    instrument_id: str = ""
    data_quality: Decimal = Decimal("1")

    def __post_init__(self) -> None:
        object.__setattr__(self, "timestamp", ensure_utc(self.timestamp))
        for name in ("open", "high", "low", "close", "volume", "spread", "data_quality"):
            object.__setattr__(self, name, as_decimal(getattr(self, name)))
        if min(self.open, self.high, self.low, self.close) <= ZERO:
            raise ValueError("OHLC prices must be positive")
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ValueError("invalid OHLC range")
        if self.spread < ZERO or self.volume < ZERO:
            raise ValueError("spread and volume must not be negative")

    @classmethod
    def from_historical(cls, bar: HistoricalBarLike, *, instrument_id: str = "") -> Bar:
        """Adapt the market-data layer's completed historical bar."""

        if not bool(getattr(bar, "complete", True)):
            raise ValueError("strategies may only receive completed bars")
        return cls(
            timestamp=bar.timestamp,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=getattr(bar, "volume", ZERO),
            instrument_id=instrument_id,
        )


class FillPolicy(StrEnum):
    CONSERVATIVE = "CONSERVATIVE"
    STOP_FIRST = "STOP_FIRST"
    TARGET_FIRST = "TARGET_FIRST"
    LOWER_TIMEFRAME_WHEN_AVAILABLE = "LOWER_TIMEFRAME_WHEN_AVAILABLE"


class ExitReason(StrEnum):
    STOP = "STOP"
    TARGET = "TARGET"
    TIME = "TIME"
    SIGNAL_INVALIDATION = "SIGNAL_INVALIDATION"
    CIRCUIT_BREAKER = "CIRCUIT_BREAKER"
    END_OF_DATA = "END_OF_DATA"
    RUIN = "RUIN"


@dataclass(frozen=True, slots=True)
class Position:
    position_id: str
    instrument_id: str
    strategy_version_id: str
    direction: Direction
    quantity: Decimal
    entry_timestamp: datetime
    requested_entry: Decimal
    actual_entry: Decimal
    stop_price: Decimal
    target_price: Decimal | None
    entry_spread_cost: Decimal
    entry_slippage_cost: Decimal
    planned_risk: Decimal
    margin: Decimal
    regime: str
    candidate_score: Decimal
    risk_decision_id: str
    bars_held: int = 0
    maximum_adverse_excursion: Decimal = ZERO
    maximum_favourable_excursion: Decimal = ZERO


@dataclass(frozen=True, slots=True)
class Trade:
    trade_id: str
    instrument_id: str
    strategy_version_id: str
    direction: Direction
    quantity: Decimal
    entry_timestamp: datetime
    exit_timestamp: datetime
    requested_entry: Decimal
    actual_entry: Decimal
    requested_exit: Decimal
    actual_exit: Decimal
    stop_price: Decimal
    target_price: Decimal | None
    exit_reason: ExitReason
    gross_pnl: Decimal
    spread_cost: Decimal
    slippage_cost: Decimal
    financing_cost: Decimal
    commission: Decimal
    guaranteed_stop_premium: Decimal
    currency_conversion_cost: Decimal
    total_cost: Decimal
    net_pnl: Decimal
    holding_seconds: int
    bars_held: int
    managed_equity_before: Decimal
    managed_equity_after: Decimal
    regime: str
    opportunity_score: Decimal
    risk_decision_id: str
    maximum_adverse_excursion: Decimal = ZERO
    maximum_favourable_excursion: Decimal = ZERO


@dataclass(frozen=True, slots=True)
class EquityPoint:
    timestamp: datetime
    equity: Decimal
    peak: Decimal
    drawdown: Decimal
    exposure: Decimal = ZERO


@dataclass(frozen=True, slots=True)
class AuditEvent:
    sequence: int
    timestamp: datetime
    event_type: str
    details: dict[str, Any] = field(default_factory=dict)
