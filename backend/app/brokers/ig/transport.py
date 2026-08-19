"""Injectable HTTP transport used by the IG client.

Unit tests supply an in-memory scripted transport.  The optional httpx adapter
is imported lazily, so importing the broker package never requires network
dependencies or credentials.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from .errors import IGConfigurationError, IGTransportError


@dataclass(frozen=True, slots=True)
class IGResponse:
    status_code: int
    headers: Mapping[str, str] = field(default_factory=dict, repr=False)
    payload: Any = field(default_factory=dict, repr=False)

    def json(self) -> Any:
        return self.payload


class IGTransport(Protocol):
    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        json_body: Mapping[str, Any] | None = None,
        params: Mapping[str, Any] | None = None,
        timeout: float,
    ) -> IGResponse: ...

    async def close(self) -> None: ...


class HttpxIGTransport:
    """Small httpx adapter with no request/response body logging."""

    def __init__(self) -> None:
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - deployment concern
            raise IGConfigurationError("httpx is required for real IG Demo connectivity") from exc
        self._httpx = httpx
        self._client = httpx.AsyncClient(follow_redirects=False)

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        json_body: Mapping[str, Any] | None = None,
        params: Mapping[str, Any] | None = None,
        timeout: float,
    ) -> IGResponse:
        try:
            response = await self._client.request(
                method,
                url,
                headers=dict(headers),
                json=json_body,
                params=params,
                timeout=timeout,
            )
            try:
                payload = response.json()
            except (ValueError, UnicodeError):
                payload = {}
            return IGResponse(response.status_code, dict(response.headers), payload)
        except self._httpx.ConnectError as exc:
            raise IGTransportError(request_may_have_been_sent=False) from exc
        except (self._httpx.TimeoutException, self._httpx.TransportError) as exc:
            raise IGTransportError(request_may_have_been_sent=None) from exc

    async def close(self) -> None:
        await self._client.aclose()
