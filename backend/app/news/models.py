from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class NewsItem:
    item_id: str
    source: str
    headline: str
    url: str
    published_at: datetime
    received_at: datetime
    source_summary: str | None

    @property
    def latency_seconds(self) -> Decimal:
        return Decimal(str((self.received_at - self.published_at).total_seconds()))


@dataclass(frozen=True, slots=True)
class NewsInterpretation:
    affected_countries: tuple[str, ...]
    affected_currencies: tuple[str, ...]
    affected_markets: tuple[str, ...]
    event_type: str
    direction: str
    magnitude: Decimal
    importance: int
    expected_duration_minutes: int
    policy_implication: str
    risk_implication: str
    confidence: Decimal
    source_quality: Decimal
    validation_status: str
