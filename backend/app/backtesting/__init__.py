"""Chronological research simulation and robustness tooling."""

from typing import Any

from .data_guard import FutureDataAccessError, GuardedBarSeries, MarketView
from .models import Bar, FillPolicy

__all__ = [
    "BacktestConfig",
    "BacktestEngine",
    "BacktestResult",
    "Bar",
    "FillPolicy",
    "FutureDataAccessError",
    "GuardedBarSeries",
    "HistoricalBacktestEngine",
    "MarketView",
    "PortfolioBacktestEngine",
    "PortfolioBacktestResult",
]


def __getattr__(name: str) -> Any:
    # Keep model imports cycle-free for indicators/regimes/strategies while
    # preserving a convenient public package API.
    if name in {"BacktestConfig", "BacktestEngine", "BacktestResult", "HistoricalBacktestEngine"}:
        from .engine import BacktestConfig, BacktestEngine, BacktestResult, HistoricalBacktestEngine

        return {
            "BacktestConfig": BacktestConfig,
            "BacktestEngine": BacktestEngine,
            "BacktestResult": BacktestResult,
            "HistoricalBacktestEngine": HistoricalBacktestEngine,
        }[name]
    if name in {"PortfolioBacktestEngine", "PortfolioBacktestResult"}:
        from .portfolio_engine import PortfolioBacktestEngine, PortfolioBacktestResult

        return {
            "PortfolioBacktestEngine": PortfolioBacktestEngine,
            "PortfolioBacktestResult": PortfolioBacktestResult,
        }[name]
    raise AttributeError(name)
