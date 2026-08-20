"""Chronological research simulation and robustness tooling."""

from typing import Any

from .conversion import (
    ConversionBoundary,
    ConversionMode,
    ConversionQuote,
    ConversionStalenessPolicy,
    ConversionTimingPolicy,
    ConversionUnavailableError,
    QuoteToGbpConversionPolicy,
    QuoteToGbpResolver,
    modeled_bar_open,
)
from .data_guard import FutureDataAccessError, GuardedBarSeries, MarketView
from .fill_revalidation import FillRiskRevalidation, FillRiskRevalidationPolicy
from .models import Bar, FillPolicy
from .research_costs import ResearchCostAssumption, ResearchCostSchedule
from .sessions import MarketSessionPolicy, SessionDecision, SessionPhase

__all__ = [
    "BacktestConfig",
    "BacktestEngine",
    "BacktestResult",
    "Bar",
    "ConversionBoundary",
    "ConversionMode",
    "ConversionQuote",
    "ConversionStalenessPolicy",
    "ConversionTimingPolicy",
    "ConversionUnavailableError",
    "FillPolicy",
    "FillRiskRevalidation",
    "FillRiskRevalidationPolicy",
    "FutureDataAccessError",
    "GuardedBarSeries",
    "HistoricalBacktestEngine",
    "MarketSessionPolicy",
    "MarketView",
    "PortfolioBacktestEngine",
    "PortfolioBacktestResult",
    "QuoteToGbpConversionPolicy",
    "QuoteToGbpResolver",
    "ResearchCostAssumption",
    "ResearchCostSchedule",
    "SessionDecision",
    "SessionPhase",
    "modeled_bar_open",
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
