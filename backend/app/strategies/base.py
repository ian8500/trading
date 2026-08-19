from __future__ import annotations

from abc import ABC, abstractmethod

from app.backtesting.data_guard import MarketView
from app.opportunities import OpportunityCandidate


class Strategy(ABC):
    version_id: str

    @abstractmethod
    def evaluate(self, view: MarketView) -> OpportunityCandidate | None:
        """Evaluate only the completed, clock-guarded bars in ``view``."""
