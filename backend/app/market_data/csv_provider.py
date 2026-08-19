from __future__ import annotations

import csv
import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from app.market_data.base import HistoricalDataProvider
from app.market_data.models import (
    DataManifest,
    HistoricalBar,
    HistoricalDataset,
    InstrumentDefinition,
)
from app.market_data.validation import validate_bars


class CsvDataProvider(HistoricalDataProvider):
    name = "Local CSV"

    def __init__(self, path: Path, timezone: str = "UTC") -> None:
        self.path = path
        self.timezone = timezone

    async def fetch(
        self,
        instrument: InstrumentDefinition,
        start: datetime,
        end: datetime,
        interval: str,
    ) -> HistoricalDataset:
        rows: list[HistoricalBar] = []
        with self.path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                timestamp = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
                if timestamp.tzinfo is None:
                    raise ValueError("CSV timestamps must include timezone information")
                if start <= timestamp < end:
                    rows.append(
                        HistoricalBar(
                            timestamp=timestamp.astimezone(UTC),
                            open=Decimal(row["open"]),
                            high=Decimal(row["high"]),
                            low=Decimal(row["low"]),
                            close=Decimal(row["close"]),
                            volume=Decimal(row.get("volume", "0")),
                            complete=row.get("complete", "true").lower() == "true",
                        )
                    )
        bars = tuple(rows)
        quality = validate_bars(bars, interval)
        if not quality.valid:
            raise ValueError(f"invalid CSV market data: {quality.warnings}")
        checksum = hashlib.sha256(self.path.read_bytes()).hexdigest()
        manifest = DataManifest(
            provider=self.name,
            instrument=instrument.symbol,
            provider_symbol=instrument.provider_symbol,
            downloaded_at=datetime.now(UTC),
            start_at=bars[0].timestamp,
            end_at=bars[-1].timestamp,
            interval=interval,
            timezone=self.timezone,
            row_count=len(bars),
            missing_intervals=quality.missing_intervals,
            checksum=checksum,
            usage_note=(
                "User-supplied local CSV. Provenance and usage rights remain the user's "
                "responsibility."
            ),
            warnings=quality.warnings,
            cache_path=str(self.path),
        )
        return HistoricalDataset(instrument, interval, bars, quality, manifest)
