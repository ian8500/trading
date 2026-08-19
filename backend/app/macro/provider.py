from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from app.macro.models import EconomicEvent


class MacroEventProvider(ABC):
    @abstractmethod
    async def events(
        self, start: datetime, end: datetime, as_of: datetime
    ) -> tuple[EconomicEvent, ...]:
        """Return only versions received at or before as_of."""


class DisabledMacroProvider(MacroEventProvider):
    async def events(
        self, start: datetime, end: datetime, as_of: datetime
    ) -> tuple[EconomicEvent, ...]:
        del start, end, as_of
        return ()


class FixtureMacroProvider(MacroEventProvider):
    """Clearly labelled deterministic fixture provider for leakage and strategy tests."""

    def __init__(self, fixture_events: tuple[EconomicEvent, ...]) -> None:
        self.fixture_events = fixture_events

    async def events(
        self, start: datetime, end: datetime, as_of: datetime
    ) -> tuple[EconomicEvent, ...]:
        return tuple(
            event
            for event in self.fixture_events
            if start <= event.scheduled_at < end and event.visible_at(as_of) is not None
        )
