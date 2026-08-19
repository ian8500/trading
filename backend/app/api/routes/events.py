from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.config import Settings, get_settings
from app.news.provider import OfficialRssNewsProvider

router = APIRouter(tags=["events"])


@router.get("/events")
async def events(
    settings: Annotated[Settings, Depends(get_settings)],
    include_news: bool = True,
    limit: int = 100,
) -> list[dict[str, object]]:
    if not include_news or settings.NEWS_PROVIDER != "federal_reserve":
        return []
    output: list[dict[str, object]] = []
    for item in (await OfficialRssNewsProvider().latest())[: min(limit, 100)]:
        output.append(
            {
                "id": item.item_id,
                "scheduledAt": item.published_at.isoformat(),
                "country": "US",
                "currency": "USD",
                "name": item.headline,
                "type": "NEWS",
                "importance": "MEDIUM",
                "state": "POST_EVENT",
                "source": item.source,
                "sourceUrl": item.url,
                "affectedMarkets": [],
                "summary": item.source_summary or "",
                "receivedAt": item.received_at.isoformat(),
                "latencySeconds": float(item.latency_seconds),
            }
        )
    return output
