"""Snapshot and historical IG pricing services."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from ..base import HistoricalBar, PriceQuote
from .client import IGClient
from .errors import IGAPIError, IGConfigurationError, IGOrderSafetyError
from .markets import IGMarketsService
from .utils import decimal_or_none, epic_path, list_or_empty, mapping_or_empty, parse_ig_datetime

RESOLUTIONS = frozenset(
    {
        "SECOND",
        "MINUTE",
        "MINUTE_2",
        "MINUTE_3",
        "MINUTE_5",
        "MINUTE_10",
        "MINUTE_15",
        "MINUTE_30",
        "HOUR",
        "HOUR_2",
        "HOUR_3",
        "HOUR_4",
        "DAY",
        "WEEK",
        "MONTH",
    }
)


def _format_query_time(value: datetime) -> str:
    if value.tzinfo is None:
        raise IGConfigurationError("historical price timestamps must be timezone-aware")
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")


def _price_component(row: Mapping[str, Any], key: str, side: str) -> Decimal | None:
    value = row.get(key)
    return decimal_or_none(value.get(side)) if isinstance(value, Mapping) else None


class IGPricesService:
    def __init__(self, client: IGClient, markets: IGMarketsService | None = None) -> None:
        self.client = client
        self.markets = markets or IGMarketsService(client)

    async def snapshot(self, epic: str) -> PriceQuote:
        # Version 4 publishes an epoch UTC timestamp and current top-of-book
        # ladder; version 3's updateTime lacks an explicit timezone.
        detail = await self.markets.details(epic, version=4)
        snapshot = mapping_or_empty(detail.get("snapshot"))
        ladder = list_or_empty(snapshot.get("priceLadder"))
        top = mapping_or_empty(ladder[0]) if ladder else {}
        bid = decimal_or_none(top.get("bid", snapshot.get("bid")))
        ask = decimal_or_none(
            top.get("ask", snapshot.get("offer") if "offer" in snapshot else snapshot.get("ask"))
        )
        if bid is None or ask is None or bid <= 0 or ask <= 0 or ask < bid:
            raise IGOrderSafetyError("IG returned an invalid market price")
        timestamp = parse_ig_datetime(snapshot.get("updateTimeUTC"))
        if timestamp is None and snapshot.get("updateTimestampUTC") is not None:
            try:
                timestamp = datetime.fromtimestamp(float(snapshot["updateTimestampUTC"]), tz=UTC)
            except (TypeError, ValueError, OSError):
                timestamp = None
        if timestamp is None:
            raise IGOrderSafetyError("IG market price has no verifiable UTC timestamp")
        return PriceQuote(
            epic=epic,
            bid=bid,
            ask=ask,
            timestamp=timestamp,
            market_status=str(snapshot.get("marketStatus") or "UNKNOWN"),
            delayed=bool(snapshot.get("delayTime", 0)),
            source="IG_DEMO_SNAPSHOT",
        )

    async def history(
        self,
        epic: str,
        *,
        resolution: str = "MINUTE",
        max_points: int = 10,
        start: datetime | None = None,
        end: datetime | None = None,
        page_size: int = 0,
        page_number: int = 1,
    ) -> tuple[HistoricalBar, ...]:
        if resolution not in RESOLUTIONS:
            raise IGConfigurationError("unsupported IG historical resolution")
        if not 1 <= max_points <= 10_000 or page_size < 0 or page_number < 1:
            raise IGConfigurationError("invalid IG historical pagination")
        if (start is None) != (end is None):
            raise IGConfigurationError("both historical start and end are required")
        params: dict[str, Any] = {
            "resolution": resolution,
            "pageSize": page_size,
            "pageNumber": page_number,
        }
        if start is not None and end is not None:
            if start >= end:
                raise IGConfigurationError("historical start must precede end")
            params.update({"from": _format_query_time(start), "to": _format_query_time(end)})
        else:
            params["max"] = max_points
        payload = await self.client.request(
            "GET", f"/prices/{epic_path(epic)}", version=3, params=params
        )
        rows = list_or_empty(mapping_or_empty(payload).get("prices"))
        bars: list[HistoricalBar] = []
        for raw_row in rows:
            if not isinstance(raw_row, Mapping):
                continue
            row = mapping_or_empty(raw_row)
            timestamp = parse_ig_datetime(row.get("snapshotTimeUTC"))
            if timestamp is None:
                continue
            bars.append(
                HistoricalBar(
                    epic=epic,
                    timestamp=timestamp,
                    open_bid=_price_component(row, "openPrice", "bid"),
                    open_ask=_price_component(row, "openPrice", "ask"),
                    high_bid=_price_component(row, "highPrice", "bid"),
                    high_ask=_price_component(row, "highPrice", "ask"),
                    low_bid=_price_component(row, "lowPrice", "bid"),
                    low_ask=_price_component(row, "lowPrice", "ask"),
                    close_bid=_price_component(row, "closePrice", "bid"),
                    close_ask=_price_component(row, "closePrice", "ask"),
                    volume=decimal_or_none(row.get("lastTradedVolume")),
                )
            )
        return tuple(bars)

    async def probe_historical(self, epic: str) -> bool:
        try:
            await self.history(epic, max_points=1)
            return True
        except IGAPIError as exc:
            if exc.error_code in {
                "error.unsupported.epic",
                "unauthorised.access.to.equity.exception",
            }:
                return False
            raise
