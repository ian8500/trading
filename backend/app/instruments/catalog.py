from decimal import Decimal

from app.market_data.models import InstrumentDefinition

CORE_UNIVERSE: dict[str, InstrumentDefinition] = {
    "GBPUSD": InstrumentDefinition("GBPUSD", "GBP/USD", "FX", "USD", "GBPUSD=X", Decimal("1")),
    "EURUSD": InstrumentDefinition("EURUSD", "EUR/USD", "FX", "USD", "EURUSD=X", Decimal("1")),
    "USDJPY": InstrumentDefinition("USDJPY", "USD/JPY", "FX", "JPY", "JPY=X", Decimal("1")),
    "EURGBP": InstrumentDefinition("EURGBP", "EUR/GBP", "FX", "GBP", "EURGBP=X", Decimal("1")),
    "FTSE100": InstrumentDefinition(
        "FTSE100", "FTSE 100", "INDEX", "GBP", "^FTSE", Decimal("1"), Decimal("0.1")
    ),
    "SP500": InstrumentDefinition(
        "SP500", "S&P 500", "INDEX", "USD", "^GSPC", Decimal("1"), Decimal("0.1")
    ),
    "NASDAQ100": InstrumentDefinition(
        "NASDAQ100", "NASDAQ 100", "INDEX", "USD", "^NDX", Decimal("1"), Decimal("0.1")
    ),
    "DAX": InstrumentDefinition(
        "DAX", "DAX", "INDEX", "EUR", "^GDAXI", Decimal("1"), Decimal("0.1")
    ),
    "GOLD": InstrumentDefinition(
        "GOLD", "Gold Futures", "COMMODITY", "USD", "GC=F", Decimal("1"), Decimal("0.1")
    ),
    "BITCOIN": InstrumentDefinition(
        "BITCOIN",
        "Bitcoin / USD",
        "CRYPTO",
        "USD",
        "BTC-USD",
        Decimal("1"),
        Decimal("0.001"),
    ),
    "ETHEREUM": InstrumentDefinition(
        "ETHEREUM",
        "Ethereum / USD",
        "CRYPTO",
        "USD",
        "ETH-USD",
        Decimal("1"),
        Decimal("0.01"),
    ),
}

OFFICIAL_DAILY_SYMBOLS = (
    "GBPUSD",
    "EURUSD",
    "USDJPY",
    "EURGBP",
    "FTSE100",
    "SP500",
    "NASDAQ100",
    "DAX",
    "GOLD",
)
OFFICIAL_INTRADAY_SYMBOLS = ("GBPUSD", "EURUSD", "SP500", "NASDAQ100", "GOLD", "BITCOIN")
