"""IG v2 CST/XST authentication held only in process memory."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from .config import IGDemoConfig, validate_demo_streaming_url
from .errors import IGAuthenticationError, IGConfigurationError
from .transport import IGTransport
from .utils import list_or_empty, mapping_or_empty, require_account_id

_LOG = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def redact_text(value: object, secrets: tuple[str, ...]) -> str:
    """Return text with configured secret fragments replaced.

    This is defense in depth.  Request bodies and authentication headers are
    never intentionally passed to logging in the first place.
    """

    result = str(value)
    for secret in secrets:
        if secret:
            result = result.replace(secret, "[REDACTED]")
    return result


class IGSecretRedactingFilter(logging.Filter):
    """Logging filter suitable for a dedicated IG logger/handler."""

    def __init__(self, *secrets: str) -> None:
        super().__init__()
        self._secrets = tuple(secret for secret in secrets if secret)

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_text(record.msg, self._secrets)
        if record.args:
            if isinstance(record.args, Mapping):
                record.args = {
                    key: redact_text(value, self._secrets) for key, value in record.args.items()
                }
            else:
                record.args = tuple(redact_text(value, self._secrets) for value in record.args)
        return True


@dataclass(frozen=True, slots=True)
class IGCredentials:
    username: str = field(repr=False)
    password: str = field(repr=False)
    api_key: str = field(repr=False)
    account_id: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not self.username or not self.password or not self.api_key:
            raise IGConfigurationError("IG Demo credentials are incomplete")

    @property
    def secret_values(self) -> tuple[str, ...]:
        return tuple(
            value
            for value in (self.username, self.password, self.api_key, self.account_id)
            if value
        )


@dataclass(frozen=True, slots=True, repr=False)
class IGSession:
    client_token: str
    security_token: str
    account_id: str
    lightstreamer_endpoint: str
    created_at: datetime
    refresh_after: datetime

    def __repr__(self) -> str:
        return "IGSession(<redacted>)"

    def headers(self) -> dict[str, str]:
        return {"CST": self.client_token, "X-SECURITY-TOKEN": self.security_token}

    def streaming_password(self) -> str:
        return f"CST-{self.client_token}|XST-{self.security_token}"


class IGAuthManager:
    """Creates and conservatively renews v2 sessions.

    Official IG documentation states that v1/v2 CST/XST tokens are initially
    valid for six hours and may be extended by use up to 72 hours.  Refreshing
    here means a fresh v2 login before the conservative local deadline; tokens
    and passwords are never written to disk.
    """

    def __init__(
        self,
        config: IGDemoConfig,
        credentials: IGCredentials,
        transport: IGTransport,
        *,
        clock: Callable[[], datetime] = _utcnow,
        refresh_interval: timedelta = timedelta(hours=5, minutes=45),
    ) -> None:
        self.config = config
        self.credentials = credentials
        self.transport = transport
        self._clock = clock
        self._refresh_interval = refresh_interval
        self._session: IGSession | None = None
        self._lock = asyncio.Lock()

    @property
    def session(self) -> IGSession | None:
        return self._session

    async def login(self, *, force: bool = False) -> IGSession:
        async with self._lock:
            now = self._clock()
            if not force and self._session is not None and now < self._session.refresh_after:
                return self._session

            # Never log this request body.
            response = await self.transport.request(
                "POST",
                f"{self.config.rest_base_url}/session",
                headers={
                    "X-IG-API-KEY": self.credentials.api_key,
                    "Version": "2",
                    "Accept": "application/json; charset=UTF-8",
                    "Content-Type": "application/json",
                },
                json_body={
                    "identifier": self.credentials.username,
                    "password": self.credentials.password,
                    "encryptedPassword": False,
                },
                timeout=self.config.request_timeout_seconds,
            )
            if not 200 <= response.status_code < 300:
                self._session = None
                _LOG.warning("IG Demo authentication failed with status %s", response.status_code)
                raise IGAuthenticationError("IG Demo authentication failed")

            headers = {str(key).lower(): str(value) for key, value in response.headers.items()}
            client_token = headers.get("cst")
            security_token = headers.get("x-security-token")
            payload = mapping_or_empty(response.json())
            account_id = payload.get("currentAccountId") or payload.get("accountId")
            stream_endpoint = payload.get("lightstreamerEndpoint")
            rerouting = str(payload.get("reroutingEnvironment") or "DEMO").upper()
            if rerouting != "DEMO":
                self._session = None
                raise IGAuthenticationError("IG attempted to reroute the session outside Demo")
            if (
                not isinstance(client_token, str)
                or not client_token
                or not isinstance(security_token, str)
                or not security_token
                or not isinstance(account_id, str)
                or not account_id
                or not isinstance(stream_endpoint, str)
                or not stream_endpoint
            ):
                self._session = None
                raise IGAuthenticationError("IG Demo authentication response was incomplete")
            if payload.get("dealingEnabled") is False:
                self._session = None
                raise IGAuthenticationError("the active IG Demo account is not enabled for dealing")
            try:
                stream_endpoint = validate_demo_streaming_url(stream_endpoint)
            except IGConfigurationError:
                self._session = None
                raise

            session = IGSession(
                client_token=client_token,
                security_token=security_token,
                account_id=account_id,
                lightstreamer_endpoint=stream_endpoint,
                created_at=now,
                refresh_after=now + self._refresh_interval,
            )
            self._session = session
            if self.credentials.account_id and self.credentials.account_id != account_id:
                requested_account = require_account_id(self.credentials.account_id)
                advertised_accounts = {
                    row.get("accountId")
                    for raw_row in list_or_empty(payload.get("accounts"))
                    if (row := mapping_or_empty(raw_row)) and isinstance(row.get("accountId"), str)
                }
                if advertised_accounts and requested_account not in advertised_accounts:
                    self._session = None
                    raise IGAuthenticationError("configured IG Demo account was not discovered")
                switch_response = await self.transport.request(
                    "PUT",
                    f"{self.config.rest_base_url}/session",
                    headers={
                        "X-IG-API-KEY": self.credentials.api_key,
                        "CST": client_token,
                        "X-SECURITY-TOKEN": security_token,
                        "Version": "1",
                        "Accept": "application/json; charset=UTF-8",
                        "Content-Type": "application/json",
                    },
                    json_body={"accountId": requested_account, "defaultAccount": False},
                    timeout=self.config.request_timeout_seconds,
                )
                switched_headers = {
                    str(key).lower(): str(value) for key, value in switch_response.headers.items()
                }
                switched_xst = switched_headers.get("x-security-token")
                switch_payload = mapping_or_empty(switch_response.json())
                if (
                    not 200 <= switch_response.status_code < 300
                    or not switched_xst
                    or switch_payload.get("dealingEnabled") is False
                ):
                    self._session = None
                    raise IGAuthenticationError("configured IG Demo account could not be selected")
                session = IGSession(
                    client_token=client_token,
                    security_token=switched_xst,
                    account_id=requested_account,
                    lightstreamer_endpoint=stream_endpoint,
                    created_at=now,
                    refresh_after=now + self._refresh_interval,
                )
                self._session = session
            _LOG.info("IG Demo authentication succeeded")
            return session

    async def ensure_session(self) -> IGSession:
        return await self.login(force=False)

    async def refresh(self) -> IGSession:
        return await self.login(force=True)

    def invalidate(self) -> None:
        self._session = None

    async def logout(self) -> None:
        session = self._session
        self._session = None
        if session is None:
            return
        try:
            await self.transport.request(
                "DELETE",
                f"{self.config.rest_base_url}/session",
                headers={
                    "X-IG-API-KEY": self.credentials.api_key,
                    "CST": session.client_token,
                    "X-SECURITY-TOKEN": session.security_token,
                    "Version": "1",
                    "Accept": "application/json; charset=UTF-8",
                    "Content-Type": "application/json",
                },
                timeout=self.config.request_timeout_seconds,
            )
        except Exception:  # logout is best effort; never include exception text
            _LOG.warning("IG Demo logout did not complete")
