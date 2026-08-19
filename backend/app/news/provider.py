from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from hashlib import sha256

import httpx
from defusedxml import ElementTree

from app.news.models import NewsItem
from app.news.security import MAX_HEADLINE_LENGTH, MAX_SUMMARY_LENGTH, sanitise_untrusted_text

OFFICIAL_FEEDS = {
    "Federal Reserve": "https://www.federalreserve.gov/feeds/press_all.xml",
}


class NewsProvider(ABC):
    @abstractmethod
    async def latest(self) -> tuple[NewsItem, ...]: ...


class DisabledNewsProvider(NewsProvider):
    async def latest(self) -> tuple[NewsItem, ...]:
        return ()


class OfficialRssNewsProvider(NewsProvider):
    """Headline/URL metadata from allowlisted official feeds; no article scraping."""

    def __init__(
        self, feeds: dict[str, str] | None = None, client: httpx.AsyncClient | None = None
    ) -> None:
        self.feeds = feeds or OFFICIAL_FEEDS
        self._client = client

    async def latest(self) -> tuple[NewsItem, ...]:
        received_at = datetime.now(UTC)
        client = self._client or httpx.AsyncClient(timeout=20, follow_redirects=True)
        owns_client = self._client is None
        items: list[NewsItem] = []
        try:
            for source, url in self.feeds.items():
                response = await client.get(
                    url, headers={"User-Agent": "TradingIntelligenceResearch/0.1"}
                )
                response.raise_for_status()
                items.extend(self._parse(source, response.text, received_at))
        finally:
            if owns_client:
                await client.aclose()
        deduplicated = {item.item_id: item for item in items}
        return tuple(
            sorted(deduplicated.values(), key=lambda item: item.published_at, reverse=True)
        )

    @staticmethod
    def _parse(source: str, xml: str, received_at: datetime) -> list[NewsItem]:
        if len(xml) > 2_000_000:
            raise ValueError("RSS payload exceeds safety limit")
        root = ElementTree.fromstring(xml)
        output: list[NewsItem] = []
        for node in root.findall(".//item")[:100]:
            headline = sanitise_untrusted_text(
                node.findtext("title") or "", max_length=MAX_HEADLINE_LENGTH
            )
            url = (node.findtext("link") or "").strip()
            if not headline or not url.startswith("https://"):
                continue
            summary = sanitise_untrusted_text(
                node.findtext("description") or "", max_length=MAX_SUMMARY_LENGTH
            )
            published_raw = node.findtext("pubDate")
            try:
                published = (
                    parsedate_to_datetime(published_raw).astimezone(UTC)
                    if published_raw
                    else received_at
                )
            except (TypeError, ValueError):
                published = received_at
            item_id = sha256(f"{source}:{url}:{headline}".encode()).hexdigest()
            output.append(
                NewsItem(item_id, source, headline, url, published, received_at, summary or None)
            )
        return output
