from __future__ import annotations

import logging

import pytest
from app.brokers.ig.auth import IGCredentials, IGSecretRedactingFilter
from app.brokers.ig.broker import IGLiveBroker
from app.brokers.ig.client import IGClient
from app.brokers.ig.config import DEMO_REST_BASE_URL, IGDemoConfig
from app.brokers.ig.errors import (
    IGAuthenticationError,
    IGConfigurationError,
    IGLiveExecutionDisabled,
)
from app.brokers.ig.transport import IGResponse
from ig_fakes import ScriptedTransport, TransportStep, demo_credentials


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"environment": "LIVE"}, IGLiveExecutionDisabled),
        ({"rest_base_url": "https://api.ig.com/gateway/deal"}, IGConfigurationError),
        ({"rest_base_url": "http://demo-api.ig.com/gateway/deal"}, IGConfigurationError),
        ({"rest_base_url": "https://demo-api.ig.com/other"}, IGConfigurationError),
        ({"live_execution_enabled": True}, IGLiveExecutionDisabled),
        ({"live_broker_implementation_enabled": True}, IGLiveExecutionDisabled),
    ],
)
def test_only_exact_demo_configuration_is_accepted(kwargs, error) -> None:
    with pytest.raises(error):
        IGDemoConfig(**kwargs)
    assert IGDemoConfig().rest_base_url == DEMO_REST_BASE_URL


def test_live_broker_has_no_constructable_code_path() -> None:
    with pytest.raises(IGLiveExecutionDisabled):
        IGLiveBroker()


@pytest.mark.asyncio
async def test_absolute_or_traversal_resource_paths_never_reach_transport() -> None:
    transport = ScriptedTransport()
    client = IGClient(demo_credentials(), transport=transport)
    for path in (
        "https://api.ig.com/gateway/deal/accounts",
        "//api.ig.com/accounts",
        "/../session",
        "/%2e%2e/session",
        "/accounts\nX-Injected: true",
    ):
        with pytest.raises(IGConfigurationError):
            await client.request("GET", path, version=1)
    assert transport.calls == []


def test_credentials_session_headers_and_account_are_redacted_from_logs() -> None:
    credentials = IGCredentials(
        username="sensitive-demo-user",
        password="sensitive-demo-password",  # pragma: allowlist secret  # noqa: S106
        api_key="sensitive-demo-api-key",  # pragma: allowlist secret
        account_id="SENSITIVE-ACCOUNT",
    )
    rendered = repr(credentials)
    for secret in credentials.secret_values:
        assert secret not in rendered

    record = logging.LogRecord(
        "ig-test",
        logging.INFO,
        __file__,
        1,
        "headers=%s",
        ({"CST": "secret-cst", "X-SECURITY-TOKEN": "secret-xst"},),
        None,
    )
    filter_ = IGSecretRedactingFilter(*credentials.secret_values, "secret-cst", "secret-xst")
    assert filter_.filter(record)
    message = record.getMessage()
    assert "secret-cst" not in message
    assert "secret-xst" not in message
    assert "[REDACTED]" in message


@pytest.mark.asyncio
async def test_login_rejects_live_rerouting_and_live_stream_endpoint() -> None:
    live_reroute = IGResponse(
        200,
        {"CST": "mock-cst", "X-SECURITY-TOKEN": "mock-xst"},
        {
            "currentAccountId": "DEMO-ACCOUNT",
            "lightstreamerEndpoint": "https://demo-apd.marketdatasystems.com/lightstreamer",
            "reroutingEnvironment": "LIVE",
        },
    )
    transport = ScriptedTransport(TransportStep("POST", "/gateway/deal/session", live_reroute))
    with pytest.raises(IGAuthenticationError):
        await IGClient(demo_credentials(), transport=transport).connect()

    live_stream = IGResponse(
        200,
        {"CST": "mock-cst", "X-SECURITY-TOKEN": "mock-xst"},
        {
            "currentAccountId": "DEMO-ACCOUNT",
            "lightstreamerEndpoint": "https://apd.marketdatasystems.com/lightstreamer",
            "reroutingEnvironment": "DEMO",
        },
    )
    transport = ScriptedTransport(TransportStep("POST", "/gateway/deal/session", live_stream))
    with pytest.raises(IGConfigurationError):
        await IGClient(demo_credentials(), transport=transport).connect()
