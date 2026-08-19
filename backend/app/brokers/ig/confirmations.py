"""IG two-phase deal confirmation handling."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from .client import IGClient
from .errors import IGAPIError, IGConfigurationError
from .utils import decimal_or_none, require_deal_reference

_DEAL_STATUSES = frozenset({"ACCEPTED", "REJECTED"})
_POSITION_STATUSES = frozenset({"AMENDED", "CLOSED", "DELETED", "OPEN", "PARTIALLY_CLOSED"})
_CONFIRMATION_REASONS = frozenset(
    {
        "ACCOUNT_NOT_ENABLED_TO_TRADING",
        "ATTACHED_ORDER_LEVEL_ERROR",
        "ATTACHED_ORDER_TRAILING_STOP_ERROR",
        "CANNOT_CHANGE_STOP_TYPE",
        "CANNOT_REMOVE_STOP",
        "CLOSING_ONLY_TRADES_ACCEPTED_ON_THIS_MARKET",
        "CLOSINGS_ONLY_ACCOUNT",
        "CONFLICTING_ORDER",
        "CONTACT_SUPPORT_INSTRUMENT_ERROR",
        "CR_SPACING",
        "DUPLICATE_ORDER_ERROR",
        "EXCHANGE_MANUAL_OVERRIDE",
        "EXPIRY_LESS_THAN_SPRINT_MARKET_MIN_EXPIRY",
        "FINANCE_REPEAT_DEALING",
        "FORCE_OPEN_ON_SAME_MARKET_DIFFERENT_CURRENCY",
        "GENERAL_ERROR",
        "GOOD_TILL_DATE_IN_THE_PAST",
        "INSTRUMENT_NOT_FOUND",
        "INSTRUMENT_NOT_TRADEABLE_IN_THIS_CURRENCY",
        "INSUFFICIENT_FUNDS",
        "LEVEL_TOLERANCE_ERROR",
        "LIMIT_ORDER_WRONG_SIDE_OF_MARKET",
        "MANUAL_ORDER_TIMEOUT",
        "MARGIN_ERROR",
        "MARKET_CLOSED",
        "MARKET_CLOSED_WITH_EDITS",
        "MARKET_CLOSING",
        "MARKET_NOT_BORROWABLE",
        "MARKET_OFFLINE",
        "MARKET_ORDERS_NOT_ALLOWED_ON_INSTRUMENT",
        "MARKET_PHONE_ONLY",
        "MARKET_ROLLED",
        "MARKET_UNAVAILABLE_TO_CLIENT",
        "MAX_AUTO_SIZE_EXCEEDED",
        "MINIMUM_ORDER_SIZE_ERROR",
        "MOVE_AWAY_ONLY_LIMIT",
        "MOVE_AWAY_ONLY_STOP",
        "MOVE_AWAY_ONLY_TRIGGER_LEVEL",
        "NCR_POSITIONS_ON_CR_ACCOUNT",
        "OPPOSING_DIRECTION_ORDERS_NOT_ALLOWED",
        "OPPOSING_POSITIONS_NOT_ALLOWED",
        "ORDER_DECLINED",
        "ORDER_LOCKED",
        "ORDER_NOT_FOUND",
        "ORDER_SIZE_CANNOT_BE_FILLED",
        "OVER_NORMAL_MARKET_SIZE",
        "PARTIALY_CLOSED_POSITION_NOT_DELETED",
        "POSITION_ALREADY_EXISTS_IN_OPPOSITE_DIRECTION",
        "POSITION_NOT_AVAILABLE_TO_CANCEL",
        "POSITION_NOT_AVAILABLE_TO_CLOSE",
        "POSITION_NOT_FOUND",
        "REJECT_CFD_ORDER_ON_SPREADBET_ACCOUNT",
        "REJECT_SPREADBET_ORDER_ON_CFD_ACCOUNT",
        "SIZE_INCREMENT",
        "SPRINT_MARKET_EXPIRY_AFTER_MARKET_CLOSE",
        "STOP_OR_LIMIT_NOT_ALLOWED",
        "STOP_REQUIRED_ERROR",
        "STRIKE_LEVEL_TOLERANCE",
        "SUCCESS",
        "TRAILING_STOP_NOT_ALLOWED",
        "UNKNOWN",
        "WRONG_SIDE_OF_MARKET",
    }
)


def _allowlisted_code(value: Any, allowed: frozenset[str], *, default: str) -> str:
    candidate = str(value or default)
    return candidate if candidate in allowed else default


@dataclass(frozen=True, slots=True)
class IGConfirmation:
    deal_reference: str
    deal_status: str
    deal_id: str | None
    status: str | None
    reason: str | None
    epic: str | None
    stop_level: Decimal | None
    stop_distance: Decimal | None
    limit_level: Decimal | None
    raw: Mapping[str, Any] = field(repr=False)

    @property
    def accepted(self) -> bool:
        return self.deal_status == "ACCEPTED"


def parse_confirmation(payload: Mapping[str, Any]) -> IGConfirmation:
    return IGConfirmation(
        deal_reference=str(payload.get("dealReference") or ""),
        deal_status=_allowlisted_code(payload.get("dealStatus"), _DEAL_STATUSES, default="UNKNOWN"),
        deal_id=str(payload["dealId"]) if payload.get("dealId") else None,
        status=(
            _allowlisted_code(payload["status"], _POSITION_STATUSES, default="UNKNOWN")
            if payload.get("status")
            else None
        ),
        reason=(
            _allowlisted_code(payload["reason"], _CONFIRMATION_REASONS, default="UNKNOWN")
            if payload.get("reason")
            else None
        ),
        epic=str(payload["epic"]) if payload.get("epic") else None,
        stop_level=decimal_or_none(payload.get("stopLevel")),
        stop_distance=decimal_or_none(payload.get("stopDistance")),
        limit_level=decimal_or_none(payload.get("limitLevel")),
        raw=dict(payload),
    )


class IGConfirmationsService:
    def __init__(
        self,
        client: IGClient,
        *,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
        stream_wait_seconds: float = 0.75,
        stream_cache_size: int = 1_000,
    ) -> None:
        if stream_wait_seconds < 0 or stream_cache_size < 1:
            raise ValueError("invalid IG confirmation stream settings")
        self.client = client
        self._sleep = sleeper
        self._stream_wait_seconds = stream_wait_seconds
        self._stream_cache_size = stream_cache_size
        self._stream_available = False
        self._stream_cache: OrderedDict[str, IGConfirmation] = OrderedDict()
        self._stream_waiters: dict[str, asyncio.Event] = {}

    def set_streaming_available(self, available: bool) -> None:
        self._stream_available = available
        if not available:
            # Wake waiters so they can immediately use the documented REST
            # fallback after a stream disconnect/close.
            for waiter in self._stream_waiters.values():
                waiter.set()

    def ingest_stream_confirmation(self, payload: Mapping[str, Any]) -> None:
        """Accept one decoded ``CONFIRMS`` field from ``TRADE:{account}``."""

        confirmation = parse_confirmation(payload)
        try:
            deal_reference = require_deal_reference(confirmation.deal_reference)
        except IGConfigurationError:
            return
        if confirmation.deal_status not in {"ACCEPTED", "REJECTED"}:
            return
        self._stream_cache[deal_reference] = confirmation
        self._stream_cache.move_to_end(deal_reference)
        while len(self._stream_cache) > self._stream_cache_size:
            self._stream_cache.popitem(last=False)
        waiter = self._stream_waiters.get(deal_reference)
        if waiter is not None:
            waiter.set()

    def _cached(self, deal_reference: str) -> IGConfirmation | None:
        confirmation = self._stream_cache.get(deal_reference)
        if confirmation is not None:
            self._stream_cache.move_to_end(deal_reference)
        return confirmation

    async def get(self, deal_reference: str) -> IGConfirmation | None:
        deal_reference = require_deal_reference(deal_reference)
        cached = self._cached(deal_reference)
        if cached is not None:
            return cached
        try:
            payload = await self.client.request(
                "GET", f"/confirms/{deal_reference}", version=1, allow_auth_retry=True
            )
        except IGAPIError as exc:
            if exc.status_code == 404 and exc.error_code == "error.confirms.deal-not-found":
                return None
            raise
        if not isinstance(payload, Mapping):
            return None
        confirmation = parse_confirmation(payload)
        if confirmation.deal_reference and confirmation.deal_reference != deal_reference:
            return None
        return confirmation

    async def wait_for(
        self,
        deal_reference: str,
        *,
        attempts: int = 12,
        delay_seconds: float = 0.5,
    ) -> IGConfirmation | None:
        if attempts < 1:
            raise ValueError("confirmation attempts must be positive")
        deal_reference = require_deal_reference(deal_reference)
        cached = self._cached(deal_reference)
        if cached is not None:
            return cached
        if self._stream_available and self._stream_wait_seconds > 0:
            waiter = self._stream_waiters.setdefault(deal_reference, asyncio.Event())
            # Close the race between the first cache lookup and waiter setup.
            cached = self._cached(deal_reference)
            if cached is None:
                try:
                    await asyncio.wait_for(waiter.wait(), timeout=self._stream_wait_seconds)
                except TimeoutError:
                    pass
                finally:
                    if self._stream_waiters.get(deal_reference) is waiter:
                        self._stream_waiters.pop(deal_reference, None)
            elif self._stream_waiters.get(deal_reference) is waiter:
                self._stream_waiters.pop(deal_reference, None)
            cached = self._cached(deal_reference)
            if cached is not None:
                return cached
        for attempt in range(attempts):
            result = await self.get(deal_reference)
            if result is not None:
                return result
            if attempt + 1 < attempts:
                await self._sleep(delay_seconds)
        return None
