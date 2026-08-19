"""IG integration exceptions with deliberately non-sensitive messages."""

from __future__ import annotations


class IGError(RuntimeError):
    """Base class for all IG integration failures."""


def safe_broker_code(value: object, *, default: str = "UNKNOWN") -> str:
    """Keep enum-like broker codes useful without reflecting arbitrary text."""

    return (
        "".join(character for character in str(value) if character.isalnum() or character in "._-")[
            :160
        ]
        or default
    )


class IGConfigurationError(IGError):
    pass


class IGLiveExecutionDisabled(IGConfigurationError):
    def __init__(self) -> None:
        super().__init__("IG Live execution is not implemented or permitted in V1")


class IGTransportError(IGError):
    """Network failure.

    ``request_may_have_been_sent`` is intentionally conservative.  A true or
    unknown value on a trading call must be treated as an ambiguous outcome.
    """

    def __init__(
        self,
        message: str = "IG transport failure",
        *,
        request_may_have_been_sent: bool | None = None,
    ):
        super().__init__(message)
        self.request_may_have_been_sent = request_may_have_been_sent


class IGAPIError(IGError):
    def __init__(self, status_code: int, error_code: str = "unknown") -> None:
        self.status_code = int(status_code)
        # IG error codes are useful operationally; bodies and headers are not.
        self.error_code = safe_broker_code(error_code, default="unknown")
        super().__init__(f"IG API request failed ({self.status_code}, {self.error_code})")


class IGAuthenticationError(IGError):
    pass


class IGStreamingError(IGError):
    pass


class IGOrderSafetyError(IGError):
    pass


class IGAmbiguousResponseError(IGError):
    pass


class IGOrderRejected(IGError):
    def __init__(self, reason: str = "UNKNOWN") -> None:
        # Confirmation reasons should be documented enum-like broker codes.  Do
        # not allow an unexpected response value to reflect credentials or
        # arbitrary response text into logs/exception telemetry.
        self.reason = safe_broker_code(reason)
        super().__init__(f"IG Demo order rejected ({self.reason})")


class IGProtectiveStopError(IGOrderSafetyError):
    pass


class IGReconciliationError(IGOrderSafetyError):
    pass
