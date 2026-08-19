"""Immutable IG Demo endpoint policy.

The endpoint cannot be selected by an environment-derived hostname.  That is
intentional: a typo must fail closed rather than fall through to Production.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from .errors import IGConfigurationError, IGLiveExecutionDisabled

DEMO_REST_BASE_URL = "https://demo-api.ig.com/gateway/deal"
DEMO_REST_HOST_ALLOWLIST = frozenset({"demo-api.ig.com"})

# IG says to use the endpoint returned by /session and not hard-code it.  V1
# additionally applies this allowlist before passing that endpoint to a client.
# If IG changes the Demo endpoint, this code and its tests must be reviewed.
DEMO_STREAMING_HOST_ALLOWLIST = frozenset({"demo-apd.marketdatasystems.com"})


def _validated_https_url(url: str, *, hosts: frozenset[str], exact_path: str | None = None) -> str:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise IGConfigurationError("invalid IG endpoint") from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname not in hosts
        or port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise IGConfigurationError("endpoint is not on the IG Demo allowlist")
    if exact_path is not None and parsed.path.rstrip("/") != exact_path:
        raise IGConfigurationError("unexpected IG Demo gateway path")
    return url.rstrip("/")


def validate_demo_rest_url(url: str) -> str:
    return _validated_https_url(url, hosts=DEMO_REST_HOST_ALLOWLIST, exact_path="/gateway/deal")


def validate_demo_streaming_url(url: str) -> str:
    return _validated_https_url(url, hosts=DEMO_STREAMING_HOST_ALLOWLIST)


@dataclass(frozen=True, slots=True)
class IGDemoConfig:
    environment: str = "DEMO"
    rest_base_url: str = DEMO_REST_BASE_URL
    live_execution_enabled: bool = False
    live_broker_implementation_enabled: bool = False
    request_timeout_seconds: float = 10.0
    maximum_quote_age_seconds: float = 5.0

    def __post_init__(self) -> None:
        if self.environment != "DEMO":
            raise IGLiveExecutionDisabled()
        if self.live_execution_enabled or self.live_broker_implementation_enabled:
            raise IGLiveExecutionDisabled()
        validated = validate_demo_rest_url(self.rest_base_url)
        if validated != DEMO_REST_BASE_URL:
            # Even another allowlisted path/alias needs a code change in V1.
            raise IGConfigurationError("custom IG REST endpoints are disabled")
        if self.request_timeout_seconds <= 0 or self.maximum_quote_age_seconds <= 0:
            raise IGConfigurationError("IG timeouts and quote age must be positive")
