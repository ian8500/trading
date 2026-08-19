"""Explicit clocks for wall-clock, simulation and historical replay paths."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(UTC)


class Clock(ABC):
    @abstractmethod
    def now(self) -> datetime:
        """Return the time that the caller is permitted to observe."""


class SystemClock(Clock):
    def now(self) -> datetime:
        return datetime.now(UTC)


@dataclass(slots=True)
class SimulationClock(Clock):
    _current: datetime

    def __post_init__(self) -> None:
        self._current = ensure_utc(self._current)

    def now(self) -> datetime:
        return self._current

    def advance_to(self, timestamp: datetime) -> datetime:
        timestamp = ensure_utc(timestamp)
        if timestamp < self._current:
            raise ClockAnomalyError(
                f"simulation clock cannot move backwards: {timestamp.isoformat()} "
                f"< {self._current.isoformat()}"
            )
        self._current = timestamp
        return self._current

    def advance(self, delta: timedelta) -> datetime:
        if delta < timedelta(0):
            raise ClockAnomalyError("simulation clock cannot advance by a negative duration")
        self._current += delta
        return self._current


class ReplaySpeed(StrEnum):
    STEP = "STEP"
    X1 = "1x"
    X10 = "10x"
    X100 = "100x"
    MAX = "MAX"


@dataclass(slots=True)
class ReplayClock(SimulationClock):
    speed: ReplaySpeed = ReplaySpeed.STEP


class ClockAnomalyError(RuntimeError):
    pass
