"""Open position, working order, protection and close operations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from ..base import BrokerPosition, Direction
from .client import IGClient
from .errors import IGConfigurationError
from .utils import (
    decimal_or_none,
    list_or_empty,
    mapping_or_empty,
    parse_ig_datetime,
    require_deal_id,
)


@dataclass(frozen=True, slots=True)
class IGWorkingOrder:
    deal_id: str
    epic: str
    direction: Direction
    size: Decimal
    order_type: str
    order_level: Decimal | None
    stop_distance: Decimal | None
    guaranteed_stop: bool
    raw: Mapping[str, Any] = field(repr=False)


class IGPositionsService:
    def __init__(self, client: IGClient) -> None:
        self.client = client

    async def list(self) -> tuple[BrokerPosition, ...]:
        payload = await self.client.request("GET", "/positions", version=2)
        rows = list_or_empty(mapping_or_empty(payload).get("positions"))
        results: list[BrokerPosition] = []
        for raw_row in rows:
            if not isinstance(raw_row, Mapping):
                continue
            row = mapping_or_empty(raw_row)
            position = mapping_or_empty(row.get("position"))
            market = mapping_or_empty(row.get("market"))
            parsed = self._parse_position(position, market)
            if parsed is not None:
                results.append(parsed)
        return tuple(results)

    async def get(self, deal_id: str) -> BrokerPosition | None:
        deal_id = require_deal_id(deal_id)
        payload = await self.client.request("GET", f"/positions/{deal_id}", version=2)
        if not isinstance(payload, Mapping):
            return None
        position = mapping_or_empty(payload.get("position"))
        market = mapping_or_empty(payload.get("market"))
        return self._parse_position(position, market)

    async def pending_orders(self) -> tuple[IGWorkingOrder, ...]:
        payload = await self.client.request("GET", "/working-orders", version=2)
        payload_mapping = mapping_or_empty(payload)
        rows = list_or_empty(
            payload_mapping.get("workingOrders", payload_mapping.get("working-orders"))
        )
        results: list[IGWorkingOrder] = []
        for raw_row in rows:
            if not isinstance(raw_row, Mapping):
                continue
            row = mapping_or_empty(raw_row)
            data = mapping_or_empty(row.get("workingOrderData"))
            deal_id = data.get("dealId")
            epic = data.get("epic")
            size = decimal_or_none(data.get("orderSize"))
            if not isinstance(deal_id, str) or not isinstance(epic, str) or size is None:
                continue
            results.append(
                IGWorkingOrder(
                    deal_id=deal_id,
                    epic=epic,
                    direction=Direction(str(data.get("direction") or "BUY")),
                    size=size,
                    order_type=str(data.get("orderType") or "UNKNOWN"),
                    order_level=decimal_or_none(data.get("orderLevel")),
                    stop_distance=decimal_or_none(data.get("stopDistance")),
                    guaranteed_stop=bool(data.get("guaranteedStop")),
                    raw=dict(row),
                )
            )
        return tuple(results)

    async def update_protection(
        self,
        deal_id: str,
        *,
        stop_level: Decimal | None = None,
        limit_level: Decimal | None = None,
        guaranteed_stop: bool = False,
    ) -> str:
        deal_id = require_deal_id(deal_id)
        if stop_level is None and limit_level is None:
            raise IGConfigurationError("a stop or limit level is required")
        body: dict[str, Any] = {
            "guaranteedStop": guaranteed_stop,
            "trailingStop": False,
        }
        if stop_level is not None:
            body["stopLevel"] = float(stop_level)
        if limit_level is not None:
            body["limitLevel"] = float(limit_level)
        payload = await self.client.request(
            "PUT",
            f"/positions/otc/{deal_id}",
            version=2,
            json_body=body,
            allow_auth_retry=False,
        )
        if not isinstance(payload, Mapping):
            raise IGConfigurationError("IG protection update acknowledgement was incomplete")
        deal_reference = payload.get("dealReference")
        if not isinstance(deal_reference, str):
            raise IGConfigurationError("IG protection update acknowledgement was incomplete")
        return deal_reference

    async def close_position(self, position: BrokerPosition, *, size: Decimal | None = None) -> str:
        close_size = size or position.size
        if close_size <= 0 or close_size > position.size:
            raise IGConfigurationError("invalid IG close size")
        payload = await self.client.request(
            "DELETE",
            "/positions/otc",
            version=1,
            json_body={
                "dealId": require_deal_id(position.deal_id),
                "direction": "SELL" if position.direction == Direction.BUY else "BUY",
                "size": float(close_size),
                "orderType": "MARKET",
                "timeInForce": "FILL_OR_KILL",
            },
            allow_auth_retry=False,
        )
        if not isinstance(payload, Mapping):
            raise IGConfigurationError("IG close acknowledgement was incomplete")
        deal_reference = payload.get("dealReference")
        if not isinstance(deal_reference, str):
            raise IGConfigurationError("IG close acknowledgement was incomplete")
        return deal_reference

    @staticmethod
    def _parse_position(
        position: Mapping[str, Any], market: Mapping[str, Any]
    ) -> BrokerPosition | None:
        deal_id = position.get("dealId")
        epic = market.get("epic") or position.get("epic")
        size = decimal_or_none(position.get("size"))
        level = decimal_or_none(position.get("level"))
        direction = str(position.get("direction") or "")
        if (
            not isinstance(deal_id, str)
            or not isinstance(epic, str)
            or size is None
            or level is None
            or direction not in {"BUY", "SELL"}
        ):
            return None
        return BrokerPosition(
            deal_id=deal_id,
            deal_reference=str(position["dealReference"])
            if position.get("dealReference")
            else None,
            epic=epic,
            direction=Direction(direction),
            size=size,
            level=level,
            currency=str(position["currency"]) if position.get("currency") else None,
            stop_level=decimal_or_none(position.get("stopLevel")),
            limit_level=decimal_or_none(position.get("limitLevel")),
            controlled_risk=bool(position.get("controlledRisk")),
            created_at=parse_ig_datetime(position.get("createdDateUTC")),
        )
