from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any


@dataclass(frozen=True, slots=True)
class HistoricalBar:
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal = Decimal("0")
    complete: bool = True

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        for key in ("open", "high", "low", "close", "volume"):
            data[key] = str(data[key])
        return data


@dataclass(frozen=True, slots=True)
class InstrumentDefinition:
    symbol: str
    name: str
    asset_class: str
    currency: str
    provider_symbol: str
    point_value: Decimal = Decimal("1")
    minimum_size: Decimal = Decimal("0.01")
    margin_factor: Decimal = Decimal("0.05")
    contract_size: Decimal = Decimal("1")
    size_step: Decimal = Decimal("0.01")
    economics_version: str = "research-contract-proxy-v1"
    economics_provenance: str = (
        "Versioned research contract proxy only; not an IG product specification."
    )


@dataclass(frozen=True, slots=True)
class DataQualityReport:
    valid: bool
    row_count: int
    duplicate_timestamps: int
    non_monotonic_timestamps: int
    missing_intervals: int
    impossible_ohlc_rows: int
    non_positive_price_rows: int
    extreme_outliers: int
    timezone_ambiguous: bool
    warnings: tuple[str, ...]

    @property
    def score(self) -> Decimal:
        if self.row_count == 0:
            return Decimal("0")
        hard_errors = (
            self.duplicate_timestamps
            + self.non_monotonic_timestamps
            + self.impossible_ohlc_rows
            + self.non_positive_price_rows
        )
        soft_rate = Decimal(
            self.extreme_outliers + min(self.missing_intervals, self.row_count)
        ) / Decimal(self.row_count)
        result = (
            Decimal("1")
            - Decimal(hard_errors) / Decimal(self.row_count)
            - soft_rate * Decimal("0.1")
        )
        return max(Decimal("0"), min(Decimal("1"), result))


@dataclass(frozen=True, slots=True)
class DataManifest:
    provider: str
    instrument: str
    provider_symbol: str
    downloaded_at: datetime
    start_at: datetime
    end_at: datetime
    interval: str
    timezone: str
    row_count: int
    missing_intervals: int
    checksum: str
    usage_note: str
    warnings: tuple[str, ...]
    cache_path: str | None = None

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for key in ("downloaded_at", "start_at", "end_at"):
            data[key] = data[key].isoformat()
        data["warnings"] = list(self.warnings)
        return data


@dataclass(frozen=True, slots=True)
class HistoricalDataset:
    instrument: InstrumentDefinition
    interval: str
    bars: tuple[HistoricalBar, ...]
    quality: DataQualityReport
    manifest: DataManifest
