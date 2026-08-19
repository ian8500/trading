"""Network-free fakes shared by IG broker tests."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from app.brokers.ig.transport import IGResponse


@dataclass(slots=True)
class TransportStep:
    method: str
    path: str
    result: IGResponse | Exception


class ScriptedTransport:
    def __init__(self, *steps: TransportStep) -> None:
        self.steps = list(steps)
        self.calls: list[dict[str, Any]] = []
        self.closed = False

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
        path = urlsplit(url).path
        self.calls.append(
            {
                "method": method,
                "url": url,
                "path": path,
                "headers": dict(headers),
                "json_body": dict(json_body) if json_body else None,
                "params": dict(params) if params else None,
                "timeout": timeout,
            }
        )
        if not self.steps:
            raise AssertionError(f"unexpected transport call {method} {path}")
        step = self.steps.pop(0)
        assert (method, path) == (step.method, step.path)
        if isinstance(step.result, Exception):
            raise step.result
        return step.result

    async def close(self) -> None:
        self.closed = True


def login_response(
    *,
    cst: str = "mock-cst-token",
    xst: str = "mock-xst-token",
    account_id: str = "DEMO-ACCOUNT",
    endpoint: str = "https://demo-apd.marketdatasystems.com/lightstreamer",
) -> IGResponse:
    return IGResponse(
        200,
        {"CST": cst, "X-SECURITY-TOKEN": xst},
        {
            "currentAccountId": account_id,
            "lightstreamerEndpoint": endpoint,
            "reroutingEnvironment": "DEMO",
        },
    )


def demo_credentials(*, account_id: str | None = None):
    from app.brokers.ig.auth import IGCredentials

    return IGCredentials(
        username="mock-demo-user",
        password="mock-demo-password",  # pragma: allowlist secret  # noqa: S106
        api_key="mock-demo-api-key",  # pragma: allowlist secret
        account_id=account_id,
    )
