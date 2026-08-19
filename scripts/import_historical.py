from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from app.database.models import DataManifestRecord, HistoricalBarRecord, InstrumentRecord
from app.database.numeric import quantize_data_quality, quantize_price, quantize_volume
from app.database.session import SessionLocal
from app.instruments.catalog import CORE_UNIVERSE, OFFICIAL_DAILY_SYMBOLS, OFFICIAL_INTRADAY_SYMBOLS
from app.market_data.models import HistoricalDataset
from app.market_data.yahoo import YahooFinanceProvider
from sqlalchemy import select


def _database_timestamp(value: datetime) -> datetime:
    """Normalise timestamps for SQLite, which returns timezone columns as naive values."""
    if value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value


def persist_dataset(dataset: HistoricalDataset) -> None:
    with SessionLocal() as session:
        instrument = session.scalar(
            select(InstrumentRecord).where(InstrumentRecord.symbol == dataset.instrument.symbol)
        )
        if instrument is None:
            instrument = InstrumentRecord(
                symbol=dataset.instrument.symbol,
                name=dataset.instrument.name,
                asset_class=dataset.instrument.asset_class,
                currency=dataset.instrument.currency,
                provider_symbol=dataset.instrument.provider_symbol,
                active=True,
                capabilities={"historical": True, "intervals": [dataset.interval]},
            )
            session.add(instrument)
            session.flush()
        else:
            intervals = set(instrument.capabilities.get("intervals", []))
            intervals.add(dataset.interval)
            instrument.capabilities = {"historical": True, "intervals": sorted(intervals)}

        checksum = dataset.manifest.checksum
        manifest_exists = session.scalar(
            select(DataManifestRecord.id).where(DataManifestRecord.checksum == checksum)
        )
        if manifest_exists is None:
            session.add(
                DataManifestRecord(
                    provider=dataset.manifest.provider,
                    instrument=dataset.manifest.instrument,
                    provider_symbol=dataset.manifest.provider_symbol,
                    downloaded_at=dataset.manifest.downloaded_at,
                    start_at=dataset.manifest.start_at,
                    end_at=dataset.manifest.end_at,
                    interval=dataset.manifest.interval,
                    timezone=dataset.manifest.timezone,
                    row_count=dataset.manifest.row_count,
                    missing_intervals=dataset.manifest.missing_intervals,
                    checksum=checksum,
                    usage_note=dataset.manifest.usage_note,
                    warnings=list(dataset.manifest.warnings),
                    cache_path=dataset.manifest.cache_path,
                )
            )

        existing = {
            _database_timestamp(row.timestamp): row
            for row in session.scalars(
                select(HistoricalBarRecord).where(
                    HistoricalBarRecord.instrument_id == instrument.id,
                    HistoricalBarRecord.provider == dataset.manifest.provider,
                    HistoricalBarRecord.interval == dataset.interval,
                    HistoricalBarRecord.timestamp >= dataset.bars[0].timestamp,
                    HistoricalBarRecord.timestamp <= dataset.bars[-1].timestamp,
                )
            )
        }
        for bar in dataset.bars:
            open_price = quantize_price(bar.open)
            high_price = quantize_price(bar.high)
            low_price = quantize_price(bar.low)
            close_price = quantize_price(bar.close)
            volume = quantize_volume(bar.volume)
            data_quality = quantize_data_quality(dataset.quality.score)
            values = {
                "open": open_price,
                "high": high_price,
                "low": low_price,
                "close": close_price,
                "volume": volume,
                "complete": bar.complete,
                "data_quality": data_quality,
                "manifest_checksum": checksum,
            }
            database_timestamp = _database_timestamp(bar.timestamp)
            record = existing.get(database_timestamp)
            if record is None:
                session.add(
                    HistoricalBarRecord(
                        instrument_id=instrument.id,
                        provider=dataset.manifest.provider,
                        interval=dataset.interval,
                        timestamp=database_timestamp,
                        open=open_price,
                        high=high_price,
                        low=low_price,
                        close=close_price,
                        volume=volume,
                        complete=bar.complete,
                        data_quality=data_quality,
                        manifest_checksum=checksum,
                    )
                )
            else:
                for key, value in values.items():
                    setattr(record, key, value)
        session.commit()


async def import_preset(preset: str) -> list[dict[str, object]]:
    provider = YahooFinanceProvider(Path("data/historical"))
    if preset == "daily-core":
        symbols = OFFICIAL_DAILY_SYMBOLS
        start, end, interval = (
            datetime(2018, 1, 1, tzinfo=UTC),
            datetime(2026, 8, 19, tzinfo=UTC),
            "1d",
        )
    elif preset == "intraday-core":
        symbols = OFFICIAL_INTRADAY_SYMBOLS
        start, end, interval = (
            datetime(2024, 8, 20, tzinfo=UTC),
            datetime(2026, 8, 19, tzinfo=UTC),
            "1h",
        )
    else:
        raise ValueError(f"unknown preset: {preset}")

    manifests: list[dict[str, object]] = []
    for symbol in symbols:
        dataset = await provider.fetch(CORE_UNIVERSE[symbol], start, end, interval)
        persist_dataset(dataset)
        manifest = dataset.manifest.as_dict()
        manifests.append(manifest)
        print(
            f"{symbol}: {manifest['row_count']} {interval} bars, "
            f"{manifest['start_at']} to {manifest['end_at']}, sha256={manifest['checksum']}"
        )
    return manifests


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import genuine research-only historical market data"
    )
    parser.add_argument("--preset", choices=("daily-core", "intraday-core"), default="daily-core")
    parser.add_argument("--summary", type=Path, default=Path("data/historical/import-summary.json"))
    args = parser.parse_args()
    manifests = asyncio.run(import_preset(args.preset))
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(manifests, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
