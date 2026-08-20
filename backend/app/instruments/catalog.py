from decimal import Decimal

from app.market_data.models import InstrumentDefinition

_RESEARCH_ECONOMICS = "research-contract-proxy-v1"
_RESEARCH_PROVENANCE = "Versioned research contract proxy only; not an IG product specification."


def _definition(
    symbol: str,
    name: str,
    asset_class: str,
    currency: str,
    provider_symbol: str,
    *,
    minimum_size: Decimal = Decimal("0.01"),
    size_step: Decimal = Decimal("0.01"),
    point_value: Decimal = Decimal("1"),
    contract_size: Decimal = Decimal("1"),
    margin_factor: Decimal = Decimal("0.05"),
) -> InstrumentDefinition:
    return InstrumentDefinition(
        symbol=symbol,
        name=name,
        asset_class=asset_class,
        currency=currency,
        provider_symbol=provider_symbol,
        point_value=point_value,
        minimum_size=minimum_size,
        margin_factor=margin_factor,
        contract_size=contract_size,
        size_step=size_step,
        economics_version=_RESEARCH_ECONOMICS,
        economics_provenance=_RESEARCH_PROVENANCE,
    )


CORE_UNIVERSE: dict[str, InstrumentDefinition] = {
    "GBPUSD": _definition("GBPUSD", "GBP/USD", "FX", "USD", "GBPUSD=X"),
    "EURUSD": _definition("EURUSD", "EUR/USD", "FX", "USD", "EURUSD=X"),
    "USDJPY": _definition("USDJPY", "USD/JPY", "FX", "JPY", "JPY=X"),
    "EURGBP": _definition("EURGBP", "EUR/GBP", "FX", "GBP", "EURGBP=X"),
    "FTSE100": _definition(
        "FTSE100",
        "FTSE 100",
        "INDEX",
        "GBP",
        "^FTSE",
        minimum_size=Decimal("0.1"),
        size_step=Decimal("0.1"),
    ),
    "SP500": _definition(
        "SP500",
        "S&P 500",
        "INDEX",
        "USD",
        "^GSPC",
        minimum_size=Decimal("0.1"),
        size_step=Decimal("0.1"),
    ),
    "NASDAQ100": _definition(
        "NASDAQ100",
        "NASDAQ 100",
        "INDEX",
        "USD",
        "^NDX",
        minimum_size=Decimal("0.1"),
        size_step=Decimal("0.1"),
    ),
    "DAX": _definition(
        "DAX",
        "DAX",
        "INDEX",
        "EUR",
        "^GDAXI",
        minimum_size=Decimal("0.1"),
        size_step=Decimal("0.1"),
    ),
    "GOLD": _definition(
        "GOLD",
        "Gold Futures",
        "COMMODITY",
        "USD",
        "GC=F",
        minimum_size=Decimal("0.1"),
        size_step=Decimal("0.1"),
    ),
    "BITCOIN": _definition(
        "BITCOIN",
        "Bitcoin / USD",
        "CRYPTO",
        "USD",
        "BTC-USD",
        minimum_size=Decimal("0.001"),
        size_step=Decimal("0.001"),
    ),
    "ETHEREUM": _definition(
        "ETHEREUM",
        "Ethereum / USD",
        "CRYPTO",
        "USD",
        "ETH-USD",
        minimum_size=Decimal("0.01"),
        size_step=Decimal("0.01"),
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
