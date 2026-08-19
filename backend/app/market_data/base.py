from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from app.market_data.models import HistoricalDataset, InstrumentDefinition


class HistoricalDataProvider(ABC):
    """Point-in-time historical bars from an external or local provider."""

    name: str

    @abstractmethod
    async def fetch(
        self,
        instrument: InstrumentDefinition,
        start: datetime,
        end: datetime,
        interval: str,
    ) -> HistoricalDataset:
        """Fetch completed bars within [start, end)."""


class StreamingMarketDataProvider(ABC):
    @abstractmethod
    async def subscribe(self, symbols: tuple[str, ...]) -> None: ...


class SnapshotMarketDataProvider(ABC):
    @abstractmethod
    async def snapshot(self, symbol: str) -> dict[str, object]: ...


class BrokerDataProvider(ABC):
    @abstractmethod
    async def historical_prices(
        self, symbol: str, start: datetime, end: datetime, interval: str
    ) -> HistoricalDataset: ...
