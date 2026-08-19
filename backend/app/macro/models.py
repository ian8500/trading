from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum


class MarketEventState(StrEnum):
    NORMAL = "NORMAL"
    PRE_EVENT = "PRE_EVENT"
    RELEASE_WINDOW = "RELEASE_WINDOW"
    POST_EVENT = "POST_EVENT"


@dataclass(frozen=True, slots=True)
class EconomicEvent:
    event_id: str
    country: str
    currency: str
    event_name: str
    event_type: str
    scheduled_at: datetime
    released_at: datetime | None
    received_at: datetime | None
    importance: int
    forecast: Decimal | None
    actual: Decimal | None
    previous: Decimal | None
    revised_previous: Decimal | None
    absolute_surprise: Decimal | None
    normalised_surprise: Decimal | None
    source: str
    source_url: str
    data_version: str

    def visible_at(self, simulation_time: datetime) -> EconomicEvent | None:
        if self.received_at is None or self.received_at > simulation_time:
            return None
        return self

    def state_at(
        self,
        timestamp: datetime,
        pre_window: timedelta = timedelta(hours=1),
        release_window: timedelta = timedelta(minutes=15),
        post_window: timedelta = timedelta(hours=4),
    ) -> MarketEventState:
        if self.scheduled_at - pre_window <= timestamp < self.scheduled_at:
            return MarketEventState.PRE_EVENT
        if self.scheduled_at <= timestamp <= self.scheduled_at + release_window:
            return MarketEventState.RELEASE_WINDOW
        if self.scheduled_at + release_window < timestamp <= self.scheduled_at + post_window:
            return MarketEventState.POST_EVENT
        return MarketEventState.NORMAL
