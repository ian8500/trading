"""Market search and detail retrieval."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .client import IGClient
from .errors import IGConfigurationError
from .utils import epic_path, require_epic


@dataclass(frozen=True, slots=True)
class IGMarketSummary:
    epic: str
    name: str
    instrument_type: str
    expiry: str | None
    market_status: str


class IGMarketsService:
    def __init__(self, client: IGClient) -> None:
        self.client = client

    async def search(self, term: str) -> tuple[IGMarketSummary, ...]:
        cleaned = " ".join(term.split())
        if not cleaned or len(cleaned) > 100:
            raise IGConfigurationError("invalid IG market search term")
        payload = await self.client.request(
            "GET", "/markets", version=1, params={"searchTerm": cleaned}
        )
        rows = payload.get("markets", []) if isinstance(payload, Mapping) else []
        return self._summaries(rows)

    async def details(self, epic: str, *, version: int = 3) -> Mapping[str, Any]:
        if version not in {3, 4}:
            raise IGConfigurationError("unsupported IG market-detail version")
        payload = await self.client.request("GET", f"/markets/{epic_path(epic)}", version=version)
        if not isinstance(payload, Mapping):
            raise IGConfigurationError("IG market detail response was invalid")
        return payload

    async def details_many(self, epics: Sequence[str]) -> tuple[Mapping[str, Any], ...]:
        if not epics or len(epics) > 50:
            raise IGConfigurationError("IG market detail batch must contain 1-50 EPICs")
        cleaned = [require_epic(epic) for epic in epics]
        payload = await self.client.request(
            "GET", "/markets", version=2, params={"epics": ",".join(cleaned)}
        )
        rows = payload.get("marketDetails", []) if isinstance(payload, Mapping) else []
        return tuple(row for row in rows if isinstance(row, Mapping))

    @staticmethod
    def _summaries(rows: Any) -> tuple[IGMarketSummary, ...]:
        results: list[IGMarketSummary] = []
        if not isinstance(rows, list):
            return ()
        for row in rows:
            if not isinstance(row, Mapping) or not isinstance(row.get("epic"), str):
                continue
            results.append(
                IGMarketSummary(
                    epic=row["epic"],
                    name=str(row.get("instrumentName") or row.get("name") or row["epic"]),
                    instrument_type=str(row.get("instrumentType") or row.get("type") or "UNKNOWN"),
                    expiry=str(row["expiry"]) if row.get("expiry") is not None else None,
                    market_status=str(row.get("marketStatus") or "UNKNOWN"),
                )
            )
        return tuple(results)
