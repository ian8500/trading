"""Lightstreamer abstraction for IG Demo price and trade streams.

The protocol adapter is injected.  This module owns IG-specific item names,
credentials, endpoint validation, subscriptions and reconnect policy without
binding the application to one Lightstreamer Python package.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from .client import IGClient
from .config import validate_demo_streaming_url
from .errors import IGStreamingError
from .utils import require_epic


class IGStreamState(StrEnum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    RECONNECTING = "RECONNECTING"
    FAILED = "FAILED"


UpdateCallback = Callable[[str, Mapping[str, Any]], Awaitable[None] | None]
DisconnectCallback = Callable[[str], Awaitable[None] | None]
ConfirmationCallback = Callable[[Mapping[str, Any]], Awaitable[None] | None]


class LightstreamerAdapter(Protocol):
    async def connect(
        self,
        *,
        server_url: str,
        adapter_set: str,
        user: str,
        password: str,
        on_disconnect: DisconnectCallback,
    ) -> None: ...

    async def subscribe(
        self,
        *,
        mode: str,
        items: Sequence[str],
        fields: Sequence[str],
        data_adapter: str | None,
        on_update: UpdateCallback,
    ) -> str: ...

    async def unsubscribe(self, subscription_id: str) -> None: ...

    async def disconnect(self) -> None: ...


@dataclass(frozen=True, slots=True)
class IGStreamEvent:
    item: str
    values: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class _SubscriptionSpec:
    mode: str
    items: tuple[str, ...]
    fields: tuple[str, ...]
    data_adapter: str | None


class IGStreamingService:
    MAX_SUBSCRIPTIONS = 40
    # This is a deliberately bounded local batch size, separate from IG's
    # documented quota of 40 Lightstreamer Subscription objects.
    MAX_PRICE_ITEMS_PER_SUBSCRIPTION = 40
    PRICE_FIELDS = (
        "BIDPRICE1",
        "ASKPRICE1",
        "BIDQUOTEID",
        "ASKQUOTEID",
        "TIMESTAMP",
        "DLG_FLAG",
        "DELAY",
    )
    TRADE_FIELDS = ("CONFIRMS", "OPU", "WOU")

    def __init__(
        self,
        client: IGClient,
        adapter: LightstreamerAdapter,
        *,
        reconnect_attempts: int = 3,
        reconnect_delay_seconds: float = 0.25,
        queue_size: int = 10_000,
        confirmation_handler: ConfirmationCallback | None = None,
    ) -> None:
        self.client = client
        self.adapter = adapter
        self.reconnect_attempts = reconnect_attempts
        self.reconnect_delay_seconds = reconnect_delay_seconds
        self.state = IGStreamState.DISCONNECTED
        self.events: asyncio.Queue[IGStreamEvent] = asyncio.Queue(maxsize=queue_size)
        self._confirmation_handler = confirmation_handler
        self._specs: list[_SubscriptionSpec] = []
        self._subscription_ids: list[str] = []
        self._closed = False
        self._reconnect_lock = asyncio.Lock()

    async def connect(self) -> None:
        self._closed = False
        self.state = IGStreamState.CONNECTING
        session = await self.client.auth.ensure_session()
        endpoint = validate_demo_streaming_url(session.lightstreamer_endpoint)
        await self.adapter.connect(
            server_url=endpoint,
            adapter_set="DEFAULT",
            user=session.account_id,
            password=session.streaming_password(),
            on_disconnect=self._on_disconnect,
        )
        self.state = IGStreamState.CONNECTED

    async def subscribe_prices(self, epics: Sequence[str]) -> str:
        if not epics or len(epics) > self.MAX_PRICE_ITEMS_PER_SUBSCRIPTION:
            raise IGStreamingError("an IG price subscription requires 1-40 EPICs")
        session = await self.client.auth.ensure_session()
        items = tuple(f"PRICE:{session.account_id}:{require_epic(epic)}" for epic in epics)
        return await self._add_subscription(
            _SubscriptionSpec("MERGE", items, self.PRICE_FIELDS, "Pricing")
        )

    async def subscribe_trades(self) -> str:
        session = await self.client.auth.ensure_session()
        return await self._add_subscription(
            _SubscriptionSpec("DISTINCT", (f"TRADE:{session.account_id}",), self.TRADE_FIELDS, None)
        )

    async def _add_subscription(self, spec: _SubscriptionSpec) -> str:
        if self.state != IGStreamState.CONNECTED:
            raise IGStreamingError("IG stream is not connected")
        if len(self._specs) >= self.MAX_SUBSCRIPTIONS:
            raise IGStreamingError("IG stream subscription quota reached")
        subscription_id = await self.adapter.subscribe(
            mode=spec.mode,
            items=spec.items,
            fields=spec.fields,
            data_adapter=spec.data_adapter,
            on_update=self._on_update,
        )
        self._specs.append(spec)
        self._subscription_ids.append(subscription_id)
        return subscription_id

    async def _on_update(self, item: str, values: Mapping[str, Any]) -> None:
        if self._confirmation_handler is not None and item.startswith("TRADE:"):
            confirmation = self.decode_json_field(values.get("CONFIRMS"))
            if confirmation is not None:
                handled = self._confirmation_handler(confirmation)
                if inspect.isawaitable(handled):
                    await handled
        try:
            self.events.put_nowait(IGStreamEvent(item=item, values=dict(values)))
        except asyncio.QueueFull as exc:
            self.state = IGStreamState.FAILED
            raise IGStreamingError("IG stream consumer fell behind") from exc

    async def _on_disconnect(self, reason: str) -> None:
        await self.reconnect(reason=reason)

    async def reconnect(self, *, reason: str = "connection_lost") -> None:
        if self._closed:
            return
        async with self._reconnect_lock:
            self.state = IGStreamState.RECONNECTING
            # A token-related disconnect requires new CST/XST credentials.
            refresh_auth = any(
                word in reason.lower() for word in ("auth", "token", "cst", "xst", "401")
            )
            for attempt in range(self.reconnect_attempts):
                try:
                    if refresh_auth or attempt > 0:
                        await self.client.auth.refresh()
                    await self.adapter.disconnect()
                    await self.connect()
                    old_specs = tuple(self._specs)
                    self._subscription_ids.clear()
                    for spec in old_specs:
                        subscription_id = await self.adapter.subscribe(
                            mode=spec.mode,
                            items=spec.items,
                            fields=spec.fields,
                            data_adapter=spec.data_adapter,
                            on_update=self._on_update,
                        )
                        self._subscription_ids.append(subscription_id)
                    self.state = IGStreamState.CONNECTED
                    return
                except Exception:
                    if attempt + 1 < self.reconnect_attempts:
                        await asyncio.sleep(self.reconnect_delay_seconds)
            self.state = IGStreamState.FAILED
            raise IGStreamingError("IG Demo stream reconnect failed")

    async def close(self) -> None:
        self._closed = True
        for subscription_id in tuple(self._subscription_ids):
            with suppress(Exception):
                await self.adapter.unsubscribe(subscription_id)
        self._subscription_ids.clear()
        self._specs.clear()
        await self.adapter.disconnect()
        self.state = IGStreamState.DISCONNECTED

    async def next_event(self) -> IGStreamEvent:
        return await self.events.get()

    @staticmethod
    def decode_json_field(value: Any) -> Mapping[str, Any] | None:
        if isinstance(value, Mapping):
            return value
        if not isinstance(value, str):
            return None
        try:
            decoded = json.loads(value)
        except (ValueError, TypeError):
            return None
        return decoded if isinstance(decoded, Mapping) else None
