"""Conservative, account-specific market capability discovery."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from ..base import MarketCapability
from .markets import IGMarketsService
from .prices import IGPricesService
from .utils import decimal_or_none, list_or_empty, mapping_or_empty


def _rule_value(rules: Mapping[str, Any], name: str) -> Decimal | None:
    rule = rules.get(name)
    return decimal_or_none(rule.get("value")) if isinstance(rule, Mapping) else None


def _rule_unit(rules: Mapping[str, Any], name: str) -> str | None:
    rule = rules.get(name)
    if isinstance(rule, Mapping) and rule.get("unit") is not None:
        return str(rule["unit"])
    return None


class IGCapabilityDiscovery:
    def __init__(self, markets: IGMarketsService, prices: IGPricesService | None = None) -> None:
        self.markets = markets
        self.prices = prices

    async def discover(self, epic: str, *, probe_historical: bool = False) -> MarketCapability:
        detail = await self.markets.details(epic)
        instrument = mapping_or_empty(detail.get("instrument"))
        snapshot = mapping_or_empty(detail.get("snapshot"))
        rules = mapping_or_empty(detail.get("dealingRules"))
        currencies = list_or_empty(instrument.get("currencies"))
        default_currency = next(
            (row for row in currencies if isinstance(row, Mapping) and row.get("isDefault")),
            currencies[0] if currencies else None,
        )
        currency = (
            str(default_currency.get("code"))
            if isinstance(default_currency, Mapping) and default_currency.get("code")
            else None
        )
        margin_bands = list_or_empty(instrument.get("marginDepositBands"))
        first_band = mapping_or_empty(margin_bands[0]) if margin_bands else {}
        first_margin = first_band.get(
            "marginFactor", first_band.get("margin", instrument.get("margin"))
        )
        opening = mapping_or_empty(instrument.get("openingHours"))
        market_times = list_or_empty(opening.get("marketTimes"))
        market_status = str(snapshot.get("marketStatus") or "UNKNOWN")
        expiry = str(instrument["expiry"]) if instrument.get("expiry") is not None else None
        historical: bool | None = None
        if probe_historical:
            if self.prices is None:
                raise ValueError("a price service is required to probe historical support")
            historical = await self.prices.probe_historical(epic)

        controlled_risk = bool(instrument.get("controlledRiskAllowed"))
        market_order_preference = rules.get("marketOrderPreference")
        units = {
            name: unit
            for name in (
                "minDealSize",
                "maxDealSize",
                "minNormalStopOrLimitDistance",
                "minControlledRiskStopDistance",
            )
            if (unit := _rule_unit(rules, name)) is not None
        }
        bid = decimal_or_none(snapshot.get("bid"))
        ask = decimal_or_none(snapshot.get("offer") if "offer" in snapshot else snapshot.get("ask"))
        return MarketCapability(
            epic=str(instrument.get("epic") or epic),
            instrument_name=str(instrument.get("name") or epic),
            instrument_type=str(instrument.get("type") or "UNKNOWN"),
            currency=currency,
            market_status=market_status,
            opening_hours=tuple(row for row in market_times if isinstance(row, Mapping)),
            tradeable=market_status == "TRADEABLE",
            market_order_supported=(
                str(market_order_preference) != "NOT_AVAILABLE"
                if market_order_preference is not None
                else None
            ),
            force_open_supported=(
                bool(instrument.get("forceOpenAllowed"))
                if instrument.get("forceOpenAllowed") is not None
                else None
            ),
            stops_limits_supported=(
                bool(instrument.get("stopsLimitsAllowed"))
                if instrument.get("stopsLimitsAllowed") is not None
                else None
            ),
            snapshot_pricing_supported=bid is not None and ask is not None,
            streaming_pricing_supported=bool(instrument.get("streamingPricesAvailable")),
            historical_pricing_supported=historical,
            minimum_deal_size=_rule_value(rules, "minDealSize"),
            maximum_deal_size=_rule_value(rules, "maxDealSize"),
            contract_size=decimal_or_none(instrument.get("contractSize")),
            value_of_one_pip=decimal_or_none(instrument.get("valueOfOnePip")),
            margin_factor=decimal_or_none(first_margin),
            controlled_risk_supported=controlled_risk,
            guaranteed_stop_supported=controlled_risk,
            minimum_stop_distance=_rule_value(rules, "minNormalStopOrLimitDistance"),
            minimum_guaranteed_stop_distance=_rule_value(rules, "minControlledRiskStopDistance"),
            minimum_limit_distance=_rule_value(rules, "minNormalStopOrLimitDistance"),
            expiry=expiry,
            rolling=expiry in {"-", "DFB"},
            overnight_funding_applicable=True if expiry == "DFB" else None,
            raw_rule_units=units,
        )

    @staticmethod
    def supports_strategy(
        capability: MarketCapability,
        *,
        require_streaming: bool = False,
        require_historical: bool = False,
        require_guaranteed_stop: bool = False,
    ) -> bool:
        return bool(
            capability.tradeable
            and capability.snapshot_pricing_supported
            and capability.minimum_deal_size is not None
            and capability.raw_rule_units.get("minDealSize") == "POINTS"
            and (not require_streaming or capability.streaming_pricing_supported)
            and (not require_historical or capability.historical_pricing_supported is True)
            and (not require_guaranteed_stop or capability.guaranteed_stop_supported)
        )
