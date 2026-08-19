from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from app.brokers.ig.auth import IGAuthManager
from app.brokers.ig.client import IGClient
from app.brokers.ig.config import IGDemoConfig
from app.brokers.ig.errors import IGAuthenticationError, IGConfigurationError
from app.brokers.ig.transport import IGResponse
from ig_fakes import ScriptedTransport, TransportStep, demo_credentials, login_response


@pytest.mark.asyncio
async def test_successful_v2_authentication_keeps_tokens_in_memory() -> None:
    transport = ScriptedTransport(TransportStep("POST", "/gateway/deal/session", login_response()))
    client = IGClient(demo_credentials(), transport=transport)
    await client.connect()
    session = client.auth.session
    assert session is not None
    assert session.account_id == "DEMO-ACCOUNT"
    assert repr(session) == "IGSession(<redacted>)"
    call = transport.calls[0]
    assert call["url"] == "https://demo-api.ig.com/gateway/deal/session"
    assert call["headers"]["Version"] == "2"
    assert call["json_body"]["encryptedPassword"] is False


@pytest.mark.asyncio
async def test_authentication_failure_has_no_response_body_or_credentials() -> None:
    response = IGResponse(401, {}, {"errorCode": "error.security.invalid-details"})
    transport = ScriptedTransport(TransportStep("POST", "/gateway/deal/session", response))
    credentials = demo_credentials()
    with pytest.raises(IGAuthenticationError) as caught:
        await IGClient(credentials, transport=transport).connect()
    rendered = str(caught.value)
    assert credentials.username not in rendered
    assert credentials.password not in rendered
    assert credentials.api_key not in rendered


@pytest.mark.asyncio
async def test_expired_session_is_refreshed_once_for_get_only() -> None:
    expired = IGResponse(401, {}, {"errorCode": "error.security.client-token-invalid"})
    transport = ScriptedTransport(
        TransportStep("POST", "/gateway/deal/session", login_response(cst="first-cst")),
        TransportStep("GET", "/gateway/deal/accounts", expired),
        TransportStep("POST", "/gateway/deal/session", login_response(cst="second-cst")),
        TransportStep("GET", "/gateway/deal/accounts", IGResponse(200, {}, {"accounts": []})),
    )
    client = IGClient(demo_credentials(), transport=transport)
    assert await client.request("GET", "/accounts", version=1) == {"accounts": []}
    assert [call["method"] for call in transport.calls].count("POST") == 2
    assert transport.calls[-1]["headers"]["CST"] == "second-cst"


@pytest.mark.asyncio
async def test_mutating_requests_cannot_enable_auth_retry() -> None:
    client = IGClient(demo_credentials(), transport=ScriptedTransport())
    with pytest.raises(IGConfigurationError):
        await client.request("POST", "/positions/otc", version=2, allow_auth_retry=True)


@pytest.mark.asyncio
async def test_conservative_session_deadline_causes_fresh_login() -> None:
    now = datetime(2026, 8, 19, 10, tzinfo=UTC)
    times = iter((now, now + timedelta(hours=5, minutes=46)))
    transport = ScriptedTransport(
        TransportStep("POST", "/gateway/deal/session", login_response(cst="first")),
        TransportStep("POST", "/gateway/deal/session", login_response(cst="second")),
    )
    manager = IGAuthManager(
        IGDemoConfig(), demo_credentials(), transport, clock=lambda: next(times)
    )
    assert (await manager.ensure_session()).client_token == "first"  # noqa: S105
    assert (await manager.ensure_session()).client_token == "second"  # noqa: S105


@pytest.mark.asyncio
async def test_configured_account_is_switched_and_new_xst_is_adopted() -> None:
    transport = ScriptedTransport(
        TransportStep("POST", "/gateway/deal/session", login_response(account_id="DEFAULT")),
        TransportStep(
            "PUT",
            "/gateway/deal/session",
            IGResponse(200, {"X-SECURITY-TOKEN": "switched-xst"}, {"dealingEnabled": True}),
        ),
    )
    client = IGClient(demo_credentials(account_id="TARGET"), transport=transport)
    await client.connect()
    assert client.auth.session is not None
    assert client.auth.session.account_id == "TARGET"
    assert client.auth.session.security_token == "switched-xst"  # noqa: S105
    assert transport.calls[1]["json_body"] == {"accountId": "TARGET", "defaultAccount": False}
