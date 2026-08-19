from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx

from app.market_data.base import HistoricalDataProvider
from app.market_data.cache import write_dataset_cache, write_manifest
from app.market_data.models import (
    DataManifest,
    HistoricalBar,
    HistoricalDataset,
    InstrumentDefinition,
)
from app.market_data.validation import validate_bars

YAHOO_CHART_URL = "https://query2.finance.yahoo.com/v8/finance/chart/{symbol}"
USAGE_NOTE = (
    "Yahoo Finance public chart data; research-only, not broker-grade. The endpoint is not a "
    "contracted market-data feed and may change, contain gaps, use exchange-specific adjustments, "
    "or impose retention/rate limits. Redistribution rights are not granted by this application."
)


class YahooFinanceProvider(HistoricalDataProvider):
    name = "Yahoo Finance"

    def __init__(
        self,
        cache_root: Path | None = Path("data/historical"),
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.cache_root = cache_root
        self._client = client

    async def fetch(
        self,
        instrument: InstrumentDefinition,
        start: datetime,
        end: datetime,
        interval: str,
    ) -> HistoricalDataset:
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("start and end must be timezone-aware")
        if end <= start:
            raise ValueError("end must be after start")
        yahoo_interval = {"15m": "15m", "30m": "30m", "1h": "1h", "1d": "1d"}.get(interval)
        if yahoo_interval is None:
            raise ValueError(f"unsupported interval: {interval}")
        client = self._client or httpx.AsyncClient(
            timeout=httpx.Timeout(45),
            headers={"User-Agent": "TradingIntelligenceResearch/0.1 (local research)"},
            follow_redirects=True,
        )
        owns_client = self._client is None
        try:
            response = await client.get(
                YAHOO_CHART_URL.format(symbol=instrument.provider_symbol),
                params={
                    "period1": int(start.timestamp()),
                    "period2": int(end.timestamp()),
                    "interval": yahoo_interval,
                    "events": "history",
                    "includeAdjustedClose": "true",
                },
            )
            response.raise_for_status()
            payload = response.json()
        finally:
            if owns_client:
                await client.aclose()
        bars, provider_timezone, normalization_warnings = self._parse(payload, end, interval)
        quality = validate_bars(bars, interval)
        if normalization_warnings:
            quality = replace(quality, warnings=quality.warnings + normalization_warnings)
        if not quality.valid:
            raise ValueError(f"provider returned invalid OHLC data: {quality.warnings}")

        downloaded_at = datetime.now(UTC)
        cache_path: Path | None = None
        if self.cache_root is not None:
            cache_path, checksum = write_dataset_cache(
                self.cache_root, "yahoo", instrument.symbol, interval, bars
            )
        else:
            canonical = json.dumps([bar.as_dict() for bar in bars], sort_keys=True).encode()
            checksum = hashlib.sha256(canonical).hexdigest()
        manifest = DataManifest(
            provider=self.name,
            instrument=instrument.symbol,
            provider_symbol=instrument.provider_symbol,
            downloaded_at=downloaded_at,
            start_at=bars[0].timestamp,
            end_at=bars[-1].timestamp,
            interval=interval,
            timezone=provider_timezone,
            row_count=len(bars),
            missing_intervals=quality.missing_intervals,
            checksum=checksum,
            usage_note=USAGE_NOTE,
            warnings=quality.warnings,
            cache_path=str(cache_path) if cache_path else None,
        )
        if cache_path is not None:
            write_manifest(cache_path, manifest)
        return HistoricalDataset(instrument, interval, bars, quality, manifest)

    @staticmethod
    def _parse(
        payload: dict[str, Any], requested_end: datetime, interval: str
    ) -> tuple[tuple[HistoricalBar, ...], str, tuple[str, ...]]:
        chart = payload.get("chart", {})
        if chart.get("error"):
            raise ValueError(
                f"Yahoo Finance provider error: {chart['error'].get('code', 'unknown')}"
            )
        results = chart.get("result") or []
        if not results:
            raise ValueError("Yahoo Finance returned no chart result")
        result = results[0]
        timestamps = result.get("timestamp") or []
        quotes = ((result.get("indicators") or {}).get("quote") or [{}])[0]
        timezone_name = (result.get("meta") or {}).get("exchangeTimezoneName", "UTC")
        bars: list[HistoricalBar] = []
        normalized_rows = 0
        rejected_rows = 0
        interval_length = {
            "15m": timedelta(minutes=15),
            "30m": timedelta(minutes=30),
            "1h": timedelta(hours=1),
            "1d": timedelta(days=1),
        }[interval]
        for index, epoch in enumerate(timestamps):
            values = {
                key: (quotes.get(key) or [])[index] for key in ("open", "high", "low", "close")
            }
            if any(value is None for value in values.values()):
                continue
            # Yahoo labels candles at interval start. Domain bars are labelled at the
            # conservative completion time so their close/high/low cannot appear early.
            timestamp = datetime.fromtimestamp(epoch, tz=UTC) + interval_length
            # A candle completing at/after the exclusive end cannot be considered available.
            if timestamp >= requested_end.astimezone(UTC):
                continue
            volume_values = quotes.get("volume") or []
            volume = (
                volume_values[index] if index < len(volume_values) and volume_values[index] else 0
            )
            decimal_values = {key: Decimal(str(value)) for key, value in values.items()}
            required_high = max(decimal_values["open"], decimal_values["close"])
            required_low = min(decimal_values["open"], decimal_values["close"])
            # Yahoo occasionally reports FX high/low a few raw-feed ticks inside an endpoint.
            # Correct only sub-10bp inconsistencies, record the count, and let validation reject
            # anything larger. This is never hidden interpolation or gap filling.
            if decimal_values["high"] < required_high:
                relative_error = (required_high - decimal_values["high"]) / required_high
                if relative_error <= Decimal("0.001"):
                    decimal_values["high"] = required_high
                    normalized_rows += 1
                else:
                    rejected_rows += 1
                    continue
            if decimal_values["low"] > required_low:
                relative_error = (decimal_values["low"] - required_low) / required_low
                if relative_error <= Decimal("0.001"):
                    decimal_values["low"] = required_low
                    normalized_rows += 1
                else:
                    rejected_rows += 1
                    continue
            bars.append(
                HistoricalBar(
                    timestamp=timestamp,
                    open=decimal_values["open"],
                    high=decimal_values["high"],
                    low=decimal_values["low"],
                    close=decimal_values["close"],
                    volume=Decimal(str(volume)),
                    complete=True,
                )
            )
        if not bars:
            raise ValueError("Yahoo Finance returned no complete OHLC bars")
        warnings: tuple[str, ...] = ()
        if normalized_rows:
            warnings += (
                f"normalized {normalized_rows} sub-10bp provider high/low endpoint "
                "inconsistencies; no prices or gaps were interpolated",
            )
        if rejected_rows:
            warnings += (
                f"rejected {rejected_rows} provider rows with material impossible OHLC "
                "relationships; gaps were left explicit",
            )
        return tuple(sorted(bars, key=lambda item: item.timestamp)), timezone_name, warnings
