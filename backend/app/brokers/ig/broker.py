"""Composed IG Demo broker facade; Live intentionally cannot be constructed."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from ..base import (
    AccountSnapshot,
    Broker,
    BrokerEnvironment,
    BrokerPosition,
    MarketCapability,
    PriceQuote,
)
from .accounts import IGAccountsService
from .auth import IGCredentials
from .autonomy import IGDemoAutonomyService
from .capabilities import IGCapabilityDiscovery
from .client import IGClient
from .config import IGDemoConfig
from .confirmations import IGConfirmationsService
from .errors import IGLiveExecutionDisabled, IGStreamingError
from .markets import IGMarketsService
from .orders import IGOrdersService, SQLiteOrderIntentStore
from .positions import IGPositionsService
from .prices import IGPricesService
from .reconciliation import IGReconciliationReport, IGReconciliationService
from .safety import PersistentDemoSafetyService
from .streaming import IGStreamingService, LightstreamerAdapter
from .transport import IGTransport


class IGDemoBroker(Broker):
    environment = BrokerEnvironment.IG_DEMO

    def __init__(
        self,
        credentials: IGCredentials,
        *,
        persistence_database: str | Path,
        config: IGDemoConfig | None = None,
        transport: IGTransport | None = None,
        streaming_adapter: LightstreamerAdapter | None = None,
    ) -> None:
        self.client = IGClient(credentials, config=config, transport=transport)
        self.account_service = IGAccountsService(self.client)
        self.market_service = IGMarketsService(self.client)
        self.price_service = IGPricesService(self.client, self.market_service)
        self.capability_service = IGCapabilityDiscovery(self.market_service, self.price_service)
        self.position_service = IGPositionsService(self.client)
        self.confirmation_service = IGConfirmationsService(self.client)
        self.safety = PersistentDemoSafetyService(persistence_database)
        self.intent_store = SQLiteOrderIntentStore(persistence_database)
        self.order_service = IGOrdersService(
            self.client,
            self.confirmation_service,
            self.position_service,
            self.price_service,
            self.capability_service,
            self.intent_store,
            self.safety,
        )
        self.reconciliation_service = IGReconciliationService(
            self.position_service,
            self.intent_store,
            self.safety,
            orders=self.order_service,
        )
        self.autonomy = IGDemoAutonomyService(
            self.safety, self.position_service, self.confirmation_service
        )
        self.streaming = (
            IGStreamingService(
                self.client,
                streaming_adapter,
                confirmation_handler=self.confirmation_service.ingest_stream_confirmation,
            )
            if streaming_adapter is not None
            else None
        )

    async def connect(self) -> None:
        await self.client.connect()

    async def close(self) -> None:
        try:
            if self.streaming is not None:
                self.confirmation_service.set_streaming_available(False)
                await self.streaming.close()
        finally:
            await self.client.close()

    async def accounts(self) -> Sequence[AccountSnapshot]:
        return await self.account_service.list()

    async def market_capability(self, epic: str) -> MarketCapability:
        return await self.capability_service.discover(epic)

    async def quote(self, epic: str) -> PriceQuote:
        return await self.price_service.snapshot(epic)

    async def positions(self) -> Sequence[BrokerPosition]:
        return await self.position_service.list()

    async def reconcile(self) -> IGReconciliationReport:
        return await self.reconciliation_service.reconcile()

    async def start_streaming(self, epics: Sequence[str]) -> None:
        if self.streaming is None:
            raise IGStreamingError("no Lightstreamer adapter is configured")
        try:
            await self.streaming.connect()
            await self.streaming.subscribe_prices(epics)
            await self.streaming.subscribe_trades()
        except Exception:
            self.confirmation_service.set_streaming_available(False)
            await self.streaming.close()
            raise
        self.confirmation_service.set_streaming_available(True)


class IGLiveBroker:
    """Non-functional marker that proves Live execution has no V1 path."""

    environment = BrokerEnvironment.IG_LIVE

    def __init__(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        raise IGLiveExecutionDisabled()
