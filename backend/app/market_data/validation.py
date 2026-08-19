from __future__ import annotations

import statistics
from datetime import timedelta
from decimal import Decimal
from itertools import pairwise

from app.market_data.models import DataQualityReport, HistoricalBar

INTERVALS = {
    "15m": timedelta(minutes=15),
    "30m": timedelta(minutes=30),
    "1h": timedelta(hours=1),
    "1d": timedelta(days=1),
}


def validate_bars(bars: tuple[HistoricalBar, ...], interval: str) -> DataQualityReport:
    warnings: list[str] = []
    if not bars:
        return DataQualityReport(False, 0, 0, 0, 0, 0, 0, 0, False, ("empty dataset",))

    timestamps = [bar.timestamp for bar in bars]
    duplicate_count = len(timestamps) - len(set(timestamps))
    non_monotonic = sum(right <= left for left, right in pairwise(timestamps))
    timezone_ambiguous = any(item.tzinfo is None or item.utcoffset() is None for item in timestamps)
    non_positive = sum(
        any(price <= 0 for price in (bar.open, bar.high, bar.low, bar.close)) for bar in bars
    )
    impossible = sum(
        bar.high < max(bar.open, bar.close)
        or bar.low > min(bar.open, bar.close)
        or bar.low > bar.high
        for bar in bars
    )

    returns: list[float] = []
    for previous, current in pairwise(bars):
        if previous.close > 0:
            returns.append(float((current.close / previous.close) - Decimal("1")))
    outliers = 0
    if len(returns) >= 20:
        median = statistics.median(returns)
        deviations = [abs(item - median) for item in returns]
        mad = statistics.median(deviations)
        if mad > 0:
            outliers = sum(abs(item - median) / (1.4826 * mad) > 15 for item in returns)

    missing = _count_missing_intervals(bars, interval)
    if duplicate_count:
        warnings.append(f"{duplicate_count} duplicate timestamps")
    if non_monotonic:
        warnings.append(f"{non_monotonic} non-monotonic timestamps")
    if timezone_ambiguous:
        warnings.append("one or more timestamps have ambiguous timezone")
    if non_positive:
        warnings.append(f"{non_positive} rows contain zero or negative prices")
    if impossible:
        warnings.append(f"{impossible} rows violate OHLC relationships")
    if outliers:
        warnings.append(f"{outliers} extreme return outliers require review")
    if missing:
        warnings.append(f"{missing} expected intervals are absent; gaps were not filled")

    valid = not any((duplicate_count, non_monotonic, timezone_ambiguous, non_positive, impossible))
    return DataQualityReport(
        valid=valid,
        row_count=len(bars),
        duplicate_timestamps=duplicate_count,
        non_monotonic_timestamps=non_monotonic,
        missing_intervals=missing,
        impossible_ohlc_rows=impossible,
        non_positive_price_rows=non_positive,
        extreme_outliers=outliers,
        timezone_ambiguous=timezone_ambiguous,
        warnings=tuple(warnings),
    )


def _count_missing_intervals(bars: tuple[HistoricalBar, ...], interval: str) -> int:
    expected = INTERVALS.get(interval)
    if expected is None:
        return 0
    missing = 0
    for left, right in pairwise(bars):
        gap = right.timestamp - left.timestamp
        if interval == "1d":
            # Weekends are expected for the initial FX/index/futures universe.
            business_days = 0
            cursor = left.timestamp.date() + timedelta(days=1)
            while cursor < right.timestamp.date():
                if cursor.weekday() < 5:
                    business_days += 1
                cursor += timedelta(days=1)
            missing += business_days
        elif gap > expected * 2:
            candidate = max(0, int(gap / expected) - 1)
            # Hourly FX/equity feeds close over the weekend; do not call that missing data.
            if gap >= timedelta(hours=36) and left.timestamp.weekday() >= 4:
                candidate = 0
            missing += candidate
    return missing
