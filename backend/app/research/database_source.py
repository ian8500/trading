"""Read-only adapter from imported historical rows to a research snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backtesting.models import Bar
from app.database.models import DataManifestRecord, HistoricalBarRecord, InstrumentRecord

from .models import DataSnapshot
from .protocol import FROZEN_PROTOCOL, ResearchProtocol


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class LoadedResearchData:
    bars_by_instrument: dict[str, tuple[Bar, ...]]
    snapshot: DataSnapshot


def load_research_data(
    session: Session, protocol: ResearchProtocol = FROZEN_PROTOCOL
) -> LoadedResearchData:
    """Load exact frozen-window data without inserting or updating any row."""

    bars_by_instrument: dict[str, tuple[Bar, ...]] = {}
    checksums: dict[str, str] = {}
    for symbol in protocol.symbols:
        instrument = session.scalar(
            select(InstrumentRecord).where(InstrumentRecord.symbol == symbol)
        )
        if instrument is None:
            raise ValueError(f"{symbol} has not been imported")
        records = tuple(
            session.scalars(
                select(HistoricalBarRecord)
                .where(
                    HistoricalBarRecord.instrument_id == instrument.id,
                    HistoricalBarRecord.provider == protocol.provider,
                    HistoricalBarRecord.interval == protocol.interval,
                    HistoricalBarRecord.timestamp >= protocol.history_start.replace(tzinfo=None),
                    HistoricalBarRecord.timestamp < protocol.history_end.replace(tzinfo=None),
                    HistoricalBarRecord.complete.is_(True),
                )
                .order_by(HistoricalBarRecord.timestamp)
            )
        )
        if len(records) < 2:
            raise ValueError(f"{symbol} has insufficient completed daily research data")
        distinct_checksums = {record.manifest_checksum for record in records}
        if len(distinct_checksums) != 1:
            raise RuntimeError(
                f"{symbol} mixes data revisions in the frozen window: {sorted(distinct_checksums)}"
            )
        checksums[symbol] = distinct_checksums.pop()
        bars_by_instrument[symbol] = tuple(
            Bar(
                timestamp=_as_utc(record.timestamp),
                open=record.open,
                high=record.high,
                low=record.low,
                close=record.close,
                volume=record.volume,
                instrument_id=symbol,
                data_quality=record.data_quality,
            )
            for record in records
        )

    manifests = tuple(
        session.scalars(
            select(DataManifestRecord).where(
                DataManifestRecord.checksum.in_(sorted(set(checksums.values())))
            )
        )
    )
    manifests_by_checksum = {manifest.checksum: manifest for manifest in manifests}
    missing = set(checksums.values()) - set(manifests_by_checksum)
    if missing:
        raise RuntimeError(f"data manifests missing for checksums: {sorted(missing)}")
    manifest_ids: dict[str, str] = {}
    manifest_row_counts: dict[str, int] = {}
    manifest_missing_intervals: dict[str, int] = {}
    manifest_starts: dict[str, datetime] = {}
    manifest_ends: dict[str, datetime] = {}
    for symbol, checksum in checksums.items():
        manifest = manifests_by_checksum[checksum]
        if (
            manifest.provider != protocol.provider
            or manifest.interval != protocol.interval
            or manifest.instrument != symbol
        ):
            raise RuntimeError(f"manifest metadata does not match {symbol} frozen source")
        manifest_ids[symbol] = manifest.id
        manifest_row_counts[symbol] = manifest.row_count
        manifest_missing_intervals[symbol] = manifest.missing_intervals
        manifest_starts[symbol] = _as_utc(manifest.start_at)
        manifest_ends[symbol] = _as_utc(manifest.end_at)

    snapshot = DataSnapshot.from_bars(
        provider=protocol.provider,
        interval=protocol.interval,
        window_start=protocol.history_start,
        window_end=protocol.history_end,
        bars_by_instrument=bars_by_instrument,
        manifest_checksums=checksums,
        manifest_ids=manifest_ids,
        manifest_declared_row_counts=manifest_row_counts,
        manifest_missing_intervals=manifest_missing_intervals,
        manifest_start_at=manifest_starts,
        manifest_end_at=manifest_ends,
    )
    return LoadedResearchData(bars_by_instrument, snapshot)
