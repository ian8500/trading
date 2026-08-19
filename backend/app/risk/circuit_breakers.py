from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.core.clock import ensure_utc


class BreakerKind(StrEnum):
    DAILY_LOSS = "DAILY_LOSS"
    WEEKLY_LOSS = "WEEKLY_LOSS"
    ROLLING_DRAWDOWN = "ROLLING_DRAWDOWN"
    TOTAL_DRAWDOWN = "TOTAL_DRAWDOWN"
    MANAGED_EQUITY_INCONSISTENCY = "MANAGED_EQUITY_INCONSISTENCY"
    STALE_PRICING = "STALE_PRICING"
    DATA_FEED_DISCONNECT = "DATA_FEED_DISCONNECT"
    AUTHENTICATION_FAILURE = "AUTHENTICATION_FAILURE"
    REPEATED_REJECTED_ORDERS = "REPEATED_REJECTED_ORDERS"
    AMBIGUOUS_ORDER_STATUS = "AMBIGUOUS_ORDER_STATUS"
    FAILED_RECONCILIATION = "FAILED_RECONCILIATION"
    ABNORMAL_SPREAD = "ABNORMAL_SPREAD"
    IMPOSSIBLE_PRICE = "IMPOSSIBLE_PRICE"
    DATABASE_FAILURE = "DATABASE_FAILURE"
    STRATEGY_EXCEPTION = "STRATEGY_EXCEPTION"
    RISK_ENGINE_EXCEPTION = "RISK_ENGINE_EXCEPTION"
    CLOCK_ANOMALY = "CLOCK_ANOMALY"
    EXCESSIVE_LATENCY = "EXCESSIVE_LATENCY"
    PROTECTIVE_STOP_UNCONFIRMED = "PROTECTIVE_STOP_UNCONFIRMED"
    UNEXPECTED_BROKER_POSITION = "UNEXPECTED_BROKER_POSITION"
    ENVIRONMENT_MISCONFIGURATION = "ENVIRONMENT_MISCONFIGURATION"


@dataclass(frozen=True, slots=True)
class BreakerEvent:
    kind: BreakerKind
    timestamp: datetime
    reason: str


class CircuitBreakerRegistry:
    """Fail-closed breakers; hard faults latch while period loss gates expire."""

    def __init__(self) -> None:
        self._active: dict[BreakerKind, BreakerEvent] = {}

    @property
    def healthy(self) -> bool:
        return not self._active

    @property
    def active(self) -> tuple[BreakerEvent, ...]:
        return tuple(self._active.values())

    def trip(self, kind: BreakerKind | str, reason: str, timestamp: datetime) -> BreakerEvent:
        kind = BreakerKind(kind)
        event = BreakerEvent(kind, ensure_utc(timestamp), reason)
        self._active[kind] = event
        return event

    def reset(self, kind: BreakerKind | str) -> None:
        self._active.pop(BreakerKind(kind), None)

    def reset_all(self) -> None:
        self._active.clear()

    def reset_expired_periods(self, timestamp: datetime) -> tuple[BreakerKind, ...]:
        """Clear only loss breakers whose UTC accounting period has ended.

        Daily and weekly loss limits are temporary execution gates.  Every
        other breaker remains latched until an explicit operational reset.
        The strict comparisons also avoid silently clearing a breaker if a
        caller supplies a timestamp that moves backwards.
        """

        current = ensure_utc(timestamp)
        expired: list[BreakerKind] = []

        daily = self._active.get(BreakerKind.DAILY_LOSS)
        if daily is not None and current.date() > daily.timestamp.date():
            expired.append(BreakerKind.DAILY_LOSS)

        weekly = self._active.get(BreakerKind.WEEKLY_LOSS)
        if weekly is not None:
            current_iso = current.isocalendar()
            tripped_iso = weekly.timestamp.isocalendar()
            if (current_iso.year, current_iso.week) > (tripped_iso.year, tripped_iso.week):
                expired.append(BreakerKind.WEEKLY_LOSS)

        for kind in expired:
            self._active.pop(kind, None)
        return tuple(expired)

    def rejection_reasons(self) -> tuple[str, ...]:
        return tuple(f"circuit breaker {e.kind.value}: {e.reason}" for e in self.active)
