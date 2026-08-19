from __future__ import annotations

from bisect import bisect_right
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import overload

from app.backtesting.models import Bar
from app.core.clock import Clock, ensure_utc
from app.instruments import Instrument


class FutureDataAccessError(RuntimeError):
    """Release-blocking attempt to observe data after the simulation clock."""


class GuardedBarSeries(Sequence[Bar]):
    """Read-only bars whose every access is checked against an explicit clock."""

    def __init__(self, bars: Sequence[Bar], clock: Clock) -> None:
        self._bars = tuple(sorted(bars, key=lambda bar: bar.timestamp))
        pairs = zip(self._bars, self._bars[1:], strict=False)
        if any(a.timestamp == b.timestamp for a, b in pairs):
            raise ValueError("duplicate bar timestamps are not allowed")
        self._timestamps = tuple(bar.timestamp for bar in self._bars)
        self.clock = clock

    @property
    def visible_count(self) -> int:
        return bisect_right(self._timestamps, self.clock.now())

    def __len__(self) -> int:
        return self.visible_count

    def __iter__(self) -> Iterator[Bar]:
        return iter(self._bars[: self.visible_count])

    @overload
    def __getitem__(self, index: int) -> Bar: ...

    @overload
    def __getitem__(self, index: slice) -> tuple[Bar, ...]: ...

    def __getitem__(self, index: int | slice) -> Bar | tuple[Bar, ...]:
        visible = self.visible_count
        if isinstance(index, slice):
            start, stop, step = index.indices(len(self._bars))
            selected_indices = range(start, stop, step)
            if any(i >= visible for i in selected_indices):
                raise FutureDataAccessError("slice includes a bar after the simulation clock")
            return tuple(self._bars[index])
        normalized = index if index >= 0 else visible + index
        if normalized < 0:
            raise IndexError(index)
        return self.at(normalized)

    def at(self, index: int) -> Bar:
        if index < 0:
            index = self.visible_count + index
        if index < 0 or index >= len(self._bars):
            raise IndexError(index)
        bar = self._bars[index]
        if bar.timestamp > self.clock.now():
            raise FutureDataAccessError(
                f"bar at {bar.timestamp.isoformat()} is after simulation time "
                f"{self.clock.now().isoformat()}"
            )
        return bar

    def at_timestamp(self, timestamp: datetime) -> Bar:
        timestamp = ensure_utc(timestamp)
        if timestamp > self.clock.now():
            raise FutureDataAccessError("requested timestamp is after the simulation clock")
        index = bisect_right(self._timestamps, timestamp) - 1
        if index < 0 or self._timestamps[index] != timestamp:
            raise KeyError(timestamp)
        return self._bars[index]

    @property
    def latest(self) -> Bar:
        if not self.visible_count:
            raise LookupError("no completed bar is visible")
        return self._bars[self.visible_count - 1]

    def visible(self) -> tuple[Bar, ...]:
        return self._bars[: self.visible_count]

    def visible_tail(self, count: int) -> tuple[Bar, ...]:
        """Return at most ``count`` completed bars without exposing future data.

        Feature calculations use bounded rolling windows.  Taking the tail
        directly avoids rebuilding the entire historical prefix at every
        simulation tick while retaining the same point-in-time boundary.
        """

        if count < 0:
            raise ValueError("count cannot be negative")
        visible = self.visible_count
        start = max(0, visible - count)
        return self._bars[start:visible]

    def future(self, offset: int = 1) -> Bar:
        """Explicitly blocked API used by leakage/hostile-strategy tests."""

        index = self.visible_count - 1 + offset
        return self.at(index)


@dataclass(frozen=True, slots=True)
class MarketView:
    instrument: Instrument
    bars: GuardedBarSeries

    @property
    def now(self) -> datetime:
        return self.bars.clock.now()

    @property
    def latest(self) -> Bar:
        return self.bars.latest
