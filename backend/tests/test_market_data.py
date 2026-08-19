from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from app.market_data.models import HistoricalBar, InstrumentDefinition
from app.market_data.validation import validate_bars
from app.market_data.yahoo import YahooFinanceProvider


def bar(timestamp: datetime, price: str = "100") -> HistoricalBar:
    value = Decimal(price)
    return HistoricalBar(timestamp, value, value + 1, value - 1, value)


def test_validation_rejects_impossible_and_duplicate_bars() -> None:
    timestamp = datetime(2025, 1, 1, tzinfo=UTC)
    bad = HistoricalBar(timestamp, Decimal("100"), Decimal("90"), Decimal("80"), Decimal("100"))
    report = validate_bars((bad, bad), "1d")
    assert report.valid is False
    assert report.duplicate_timestamps == 1
    assert report.impossible_ohlc_rows == 2


def test_validation_does_not_fill_material_gap() -> None:
    start = datetime(2025, 1, 6, tzinfo=UTC)
    report = validate_bars((bar(start), bar(start + timedelta(days=3))), "1d")
    assert report.missing_intervals == 2
    assert any("not filled" in warning for warning in report.warnings)


@pytest.mark.asyncio
async def test_yahoo_parser_uses_only_complete_requested_range() -> None:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    end = datetime(2025, 1, 3, tzinfo=UTC)
    payload = {
        "chart": {
            "error": None,
            "result": [
                {
                    "meta": {"exchangeTimezoneName": "UTC"},
                    "timestamp": [
                        int(start.timestamp()),
                        int((end + timedelta(days=1)).timestamp()),
                    ],
                    "indicators": {
                        "quote": [
                            {
                                "open": [1.0, 2.0],
                                "high": [1.1, 2.1],
                                "low": [0.9, 1.9],
                                "close": [1.05, 2.05],
                                "volume": [10, 20],
                            }
                        ]
                    },
                }
            ],
        }
    }

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = YahooFinanceProvider(cache_root=None, client=client)
        dataset = await provider.fetch(
            InstrumentDefinition("TEST", "Test", "FX", "USD", "TEST=X"),
            start,
            end,
            "1d",
        )
    assert len(dataset.bars) == 1
    assert dataset.bars[0].timestamp == start + timedelta(days=1)
    assert dataset.manifest.checksum
