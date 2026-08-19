"""Allowlisted IG Demo REST client."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any

from .auth import IGAuthManager, IGCredentials
from .config import IGDemoConfig, validate_demo_rest_url
from .errors import IGAPIError, IGAuthenticationError, IGConfigurationError
from .transport import HttpxIGTransport, IGResponse, IGTransport

_LOG = logging.getLogger(__name__)

_TOKEN_ERRORS = frozenset(
    {
        "error.security.account-token-invalid",
        "error.security.account-token-missing",
        "error.security.client-token-invalid",
        "error.security.client-token-missing",
        "error.security.oauth-token-invalid",
    }
)
_RESOURCE_PATH = re.compile(r"^/[A-Za-z0-9._/-]+$")


def _validated_relative_path(path: str) -> str:
    if (
        not path.startswith("/")
        or path.startswith("//")
        or "://" in path
        or "?" in path
        or "#" in path
        or "%" in path
        or "\\" in path
        or "//" in path
        or not _RESOURCE_PATH.fullmatch(path)
        or any(part in {".", ".."} for part in path.split("/"))
    ):
        raise IGConfigurationError("invalid IG REST resource path")
    return path


def _error_code(response: IGResponse) -> str:
    payload = response.json()
    if isinstance(payload, Mapping):
        value = payload.get("errorCode") or payload.get("error")
        if isinstance(value, str):
            return value
    return "unknown"


class IGClient:
    """REST client that can only address the official Demo gateway."""

    def __init__(
        self,
        credentials: IGCredentials,
        *,
        config: IGDemoConfig | None = None,
        transport: IGTransport | None = None,
    ) -> None:
        self.config = config or IGDemoConfig()
        validate_demo_rest_url(self.config.rest_base_url)
        self.transport = transport or HttpxIGTransport()
        self.auth = IGAuthManager(self.config, credentials, self.transport)
        self.credentials = credentials

    async def connect(self) -> None:
        await self.auth.ensure_session()

    async def close(self) -> None:
        await self.auth.logout()
        await self.transport.close()

    async def request(
        self,
        method: str,
        path: str,
        *,
        version: int,
        json_body: Mapping[str, Any] | None = None,
        params: Mapping[str, Any] | None = None,
        allow_auth_retry: bool | None = None,
    ) -> Any:
        method = method.upper()
        path = _validated_relative_path(path)
        if method not in {"GET", "POST", "PUT", "DELETE"}:
            raise IGConfigurationError("unsupported IG REST method")
        if allow_auth_retry is None:
            allow_auth_retry = method == "GET"
        if method != "GET" and allow_auth_retry:
            raise IGConfigurationError("mutating IG requests cannot be automatically retried")

        url = f"{self.config.rest_base_url}{path}"
        # Re-validate the fixed base for every call, guarding against accidental
        # runtime mutation through unusual object manipulation.
        validate_demo_rest_url(self.config.rest_base_url)
        for attempt in range(2):
            session = await self.auth.ensure_session()
            headers = {
                "X-IG-API-KEY": self.credentials.api_key,
                "CST": session.client_token,
                "X-SECURITY-TOKEN": session.security_token,
                "Version": str(version),
                "Accept": "application/json; charset=UTF-8",
                "Content-Type": "application/json",
            }
            _LOG.debug("IG Demo REST %s %s", method, path)
            response = await self.transport.request(
                method,
                url,
                headers=headers,
                json_body=json_body,
                params=params,
                timeout=self.config.request_timeout_seconds,
            )
            if 200 <= response.status_code < 300:
                _LOG.debug("IG Demo REST response %s %s", path, response.status_code)
                return response.json()

            error_code = _error_code(response)
            if any(secret and secret in error_code for secret in self.credentials.secret_values):
                error_code = "redacted-error"
            if (
                attempt == 0
                and allow_auth_retry
                and response.status_code == 401
                and error_code in _TOKEN_ERRORS
            ):
                _LOG.info("Refreshing expired IG Demo session")
                await self.auth.refresh()
                continue
            if response.status_code == 401 and error_code in _TOKEN_ERRORS:
                self.auth.invalidate()
                raise IGAuthenticationError("IG Demo session is invalid")
            raise IGAPIError(response.status_code, error_code)
        raise IGAuthenticationError("IG Demo session refresh failed")  # pragma: no cover
