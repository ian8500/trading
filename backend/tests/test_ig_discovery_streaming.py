from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from app.brokers.ig.accounts import IGAccountsService
from app.brokers.ig.capabilities import IGCapabilityDiscovery
from app.brokers.ig.client import IGClient
from app.brokers.ig.confirmations import IGConfirmationsService, parse_confirmation
from app.brokers.ig.errors import IGStreamingError
from app.brokers.ig.markets import IGMarketsService
from app.brokers.ig.prices import IGPricesService
from app.brokers.ig.streaming import IGStreamingService, IGStreamState
from app.brokers.ig.transport import IGResponse
from ig_fakes import ScriptedTransport, TransportStep, demo_credentials, login_response

MARKET_DETAIL = {
    "instrument": {
        "name": "GBP/USD",
        "epic": "CS.D.GBPUSD.CFD.IP",
        "type": "CURRENCIES",
        "expiry": "DFB",
        "contractSize": "1",
        "valueOfOnePip": "1",
        "controlledRiskAllowed": True,
        "forceOpenAllowed": True,
        "stopsLimitsAllowed": True,
        "streamingPricesAvailable": True,
        "currencies": [{"code": "GBP", "isDefault": True}],
        "marginDepositBands": [{"min": 0, "max": 100, "margin": 3.33}],
        "openingHours": {"marketTimes": [{"openTime": "00:00", "closeTime": "23:59"}]},
    },
    "dealingRules": {
        "marketOrderPreference": "AVAILABLE_DEFAULT_ON",
        "minDealSize": {"unit": "POINTS", "value": 0.5},
        "minNormalStopOrLimitDistance": {"unit": "POINTS", "value": 2},
        "minControlledRiskStopDistance": {"unit": "POINTS", "value": 4},
    },
    "snapshot": {
        "bid": 1.2720,
        "offer": 1.2722,
        "priceLadder": [{"bid": "1.2720", "ask": "1.2722"}],
        "marketStatus": "TRADEABLE",
        "delayTime": 0,
        "updateTimestampUTC": 1787133600,
    },
}


@pytest.mark.asyncio
async def test_accounts_capabilities_snapshot_and_history_are_discovered() -> None:
    account_payload = {
        "accounts": [
            {
                "accountId": "DEMO-ACCOUNT",
                "accountName": "Demo CFD",
                "currency": "GBP",
                "preferred": True,
                "status": "ENABLED",
                "balance": {"balance": 10_000, "available": 9_800, "profitLoss": 12.5},
            }
        ]
    }
    history_payload = {
        "prices": [
            {
                "snapshotTimeUTC": "2026-08-19T09:59:00Z",
                "openPrice": {"bid": 1.2710, "ask": 1.2712},
                "highPrice": {"bid": 1.2721, "ask": 1.2723},
                "lowPrice": {"bid": 1.2708, "ask": 1.2710},
                "closePrice": {"bid": 1.2720, "ask": 1.2722},
                "lastTradedVolume": 20,
            }
        ]
    }
    transport = ScriptedTransport(
        TransportStep("POST", "/gateway/deal/session", login_response()),
        TransportStep("GET", "/gateway/deal/accounts", IGResponse(200, {}, account_payload)),
        TransportStep(
            "GET",
            "/gateway/deal/markets/CS.D.GBPUSD.CFD.IP",
            IGResponse(200, {}, MARKET_DETAIL),
        ),
        TransportStep(
            "GET",
            "/gateway/deal/markets/CS.D.GBPUSD.CFD.IP",
            IGResponse(200, {}, MARKET_DETAIL),
        ),
        TransportStep(
            "GET",
            "/gateway/deal/prices/CS.D.GBPUSD.CFD.IP",
            IGResponse(200, {}, history_payload),
        ),
    )
    client = IGClient(demo_credentials(), transport=transport)
    accounts = await IGAccountsService(client).list()
    assert accounts[0].balance == Decimal("10000")
    assert accounts[0].available == Decimal("9800")

    markets = IGMarketsService(client)
    prices = IGPricesService(client, markets)
    capability = await IGCapabilityDiscovery(markets, prices).discover("CS.D.GBPUSD.CFD.IP")
    assert capability.tradeable
    assert capability.streaming_pricing_supported
    assert capability.minimum_deal_size == Decimal("0.5")
    assert capability.margin_factor == Decimal("3.33")
    assert capability.guaranteed_stop_supported
    assert capability.historical_pricing_supported is None

    quote = await prices.snapshot("CS.D.GBPUSD.CFD.IP")
    assert quote.bid == Decimal("1.272")
    assert quote.ask == Decimal("1.2722")
    assert transport.calls[-1]["headers"]["Version"] == "4"
    bars = await prices.history("CS.D.GBPUSD.CFD.IP", max_points=1)
    assert bars[0].timestamp == datetime(2026, 8, 19, 9, 59, tzinfo=UTC)
    assert bars[0].close_bid == Decimal("1.272")
    assert transport.calls[-1]["headers"]["Version"] == "3"
    assert transport.calls[-1]["params"]["max"] == 1


class FakeLightstreamerAdapter:
    def __init__(self) -> None:
        self.connect_calls: list[dict[str, Any]] = []
        self.subscriptions: list[dict[str, Any]] = []
        self.disconnect_count = 0
        self.unsubscribed: list[str] = []

    async def connect(self, **kwargs: Any) -> None:
        self.connect_calls.append(kwargs)

    async def subscribe(
        self,
        *,
        mode: str,
        items: Sequence[str],
        fields: Sequence[str],
        data_adapter: str | None,
        on_update,
    ) -> str:
        self.subscriptions.append(
            {
                "mode": mode,
                "items": tuple(items),
                "fields": tuple(fields),
                "data_adapter": data_adapter,
                "on_update": on_update,
            }
        )
        return f"subscription-{len(self.subscriptions)}"

    async def unsubscribe(self, subscription_id: str) -> None:
        self.unsubscribed.append(subscription_id)

    async def disconnect(self) -> None:
        self.disconnect_count += 1


@pytest.mark.asyncio
async def test_streaming_uses_price_items_and_refreshes_tokens_on_disconnect() -> None:
    transport = ScriptedTransport(
        TransportStep("POST", "/gateway/deal/session", login_response(cst="first-cst")),
        TransportStep("POST", "/gateway/deal/session", login_response(cst="second-cst")),
    )
    client = IGClient(demo_credentials(), transport=transport)
    adapter = FakeLightstreamerAdapter()
    streaming = IGStreamingService(client, adapter, reconnect_attempts=1)
    await streaming.connect()
    await streaming.subscribe_prices(["CS.D.GBPUSD.CFD.IP"])
    await streaming.subscribe_trades()

    assert adapter.connect_calls[0]["server_url"].startswith(
        "https://demo-apd.marketdatasystems.com"
    )
    assert adapter.connect_calls[0]["user"] == "DEMO-ACCOUNT"
    assert adapter.connect_calls[0]["password"].startswith("CST-first-cst|XST-")
    assert adapter.subscriptions[0]["mode"] == "MERGE"
    assert adapter.subscriptions[0]["items"] == ("PRICE:DEMO-ACCOUNT:CS.D.GBPUSD.CFD.IP",)
    assert "TIMESTAMP" in adapter.subscriptions[0]["fields"]
    assert "DLG_FLAG" in adapter.subscriptions[0]["fields"]
    assert "UPDATE_TIME" not in adapter.subscriptions[0]["fields"]
    assert adapter.subscriptions[1]["mode"] == "DISTINCT"
    assert adapter.subscriptions[1]["items"] == ("TRADE:DEMO-ACCOUNT",)

    await streaming.reconnect(reason="token expired")
    assert streaming.state == IGStreamState.CONNECTED
    assert adapter.connect_calls[-1]["password"].startswith("CST-second-cst|XST-")
    assert len(adapter.subscriptions) == 4


@pytest.mark.asyncio
async def test_streaming_enforces_subscription_quota_and_close_clears_specs() -> None:
    transport = ScriptedTransport(
        TransportStep("POST", "/gateway/deal/session", login_response()),
    )
    client = IGClient(demo_credentials(), transport=transport)
    adapter = FakeLightstreamerAdapter()
    streaming = IGStreamingService(client, adapter)
    await streaming.connect()
    streaming.MAX_SUBSCRIPTIONS = 2
    await streaming.subscribe_prices(["CS.D.GBPUSD.CFD.IP"])
    await streaming.subscribe_trades()
    with pytest.raises(IGStreamingError, match="subscription quota"):
        await streaming.subscribe_trades()
    await streaming.close()
    assert streaming.state == IGStreamState.DISCONNECTED
    assert len(adapter.unsubscribed) == 2


@pytest.mark.asyncio
async def test_streamed_confirmation_is_preferred_without_rest_polling() -> None:
    transport = ScriptedTransport(
        TransportStep("POST", "/gateway/deal/session", login_response()),
    )
    client = IGClient(demo_credentials(), transport=transport)
    confirmations = IGConfirmationsService(client, stream_wait_seconds=0.01)
    adapter = FakeLightstreamerAdapter()
    streaming = IGStreamingService(
        client,
        adapter,
        confirmation_handler=confirmations.ingest_stream_confirmation,
    )
    await streaming.connect()
    await streaming.subscribe_trades()
    confirmations.set_streaming_available(True)
    callback = adapter.subscriptions[0]["on_update"]
    await callback(
        "TRADE:DEMO-ACCOUNT",
        {
            "CONFIRMS": json.dumps(
                {
                    "dealReference": "stream-reference",
                    "dealStatus": "ACCEPTED",
                    "dealId": "DEAL-STREAM",
                    "reason": "SUCCESS",
                }
            )
        },
    )
    result = await confirmations.wait_for("stream-reference")
    assert result is not None and result.accepted
    assert result.deal_id == "DEAL-STREAM"
    assert [call["path"] for call in transport.calls] == ["/gateway/deal/session"]


def test_streaming_json_decoder_rejects_non_objects() -> None:
    assert IGStreamingService.decode_json_field('{"dealStatus":"ACCEPTED"}') == {
        "dealStatus": "ACCEPTED"
    }
    assert IGStreamingService.decode_json_field("[]") is None
    assert IGStreamingService.decode_json_field("not-json") is None


def test_confirmation_codes_are_allowlisted_before_exposure() -> None:
    parsed = parse_confirmation(
        {
            "dealReference": "safe-reference",
            "dealStatus": "ACCEPTED credential-like-content",
            "reason": "unexpected sensitive response text",
            "status": "unexpected status",
        }
    )
    assert parsed.deal_status == "UNKNOWN"
    assert parsed.reason == "UNKNOWN"
    assert parsed.status == "UNKNOWN"
