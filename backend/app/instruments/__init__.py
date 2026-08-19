"""Provider-independent instrument catalogue and quantitative metadata."""

from .models import AssetClass, Instrument

__all__ = [
    "CORE_UNIVERSE",
    "OFFICIAL_DAILY_SYMBOLS",
    "OFFICIAL_INTRADAY_SYMBOLS",
    "AssetClass",
    "Instrument",
]


def __getattr__(name: str) -> object:
    # The catalogue's optional data-provider dependencies should not be loaded
    # merely to use the dependency-free sizing model.
    if name in {"CORE_UNIVERSE", "OFFICIAL_DAILY_SYMBOLS", "OFFICIAL_INTRADAY_SYMBOLS"}:
        from .catalog import CORE_UNIVERSE, OFFICIAL_DAILY_SYMBOLS, OFFICIAL_INTRADAY_SYMBOLS

        return {
            "CORE_UNIVERSE": CORE_UNIVERSE,
            "OFFICIAL_DAILY_SYMBOLS": OFFICIAL_DAILY_SYMBOLS,
            "OFFICIAL_INTRADAY_SYMBOLS": OFFICIAL_INTRADAY_SYMBOLS,
        }[name]
    raise AttributeError(name)
