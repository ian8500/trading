from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.backtesting.engine import BacktestConfig, BacktestResult, HistoricalBacktestEngine
from app.backtesting.models import AuditEvent, Bar
from app.core.clock import ReplayClock, ReplaySpeed


@dataclass(frozen=True, slots=True)
class ReplayEvent:
    sequence: int
    timestamp: datetime
    event_type: str
    details: dict[str, Any]


class ReplaySession:
    def __init__(
        self, events: tuple[AuditEvent, ...], speed: ReplaySpeed = ReplaySpeed.STEP
    ) -> None:
        if not events:
            raise ValueError("replay requires at least one audit event")
        self.events = events
        self.cursor = 0
        self.clock = ReplayClock(events[0].timestamp, speed=speed)

    @property
    def complete(self) -> bool:
        return self.cursor >= len(self.events)

    def step(self) -> ReplayEvent | None:
        if self.complete:
            return None
        event = self.events[self.cursor]
        self.clock.advance_to(event.timestamp)
        self.cursor += 1
        return ReplayEvent(event.sequence, event.timestamp, event.event_type, dict(event.details))

    def remaining(self) -> Iterator[ReplayEvent]:
        while not self.complete:
            event = self.step()
            if event is not None:
                yield event


class HistoricalReplay:
    """Replay consumes the exact audit stream produced by the backtest path."""

    def __init__(self, engine: HistoricalBacktestEngine) -> None:
        self.engine = engine

    def prepare(
        self,
        bars: tuple[Bar, ...],
        config: BacktestConfig | None = None,
        *,
        speed: ReplaySpeed = ReplaySpeed.STEP,
    ) -> tuple[BacktestResult, ReplaySession]:
        result = self.engine.run(bars, config)
        return result, ReplaySession(result.audit_trail, speed)
