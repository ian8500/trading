from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

SENSITIVE_KEYS = frozenset(
    {
        "password",
        "api_key",
        "apikey",
        "authorization",
        "cst",
        "x-security-token",
        "session_secret",
        "account_id",
    }
)
TOKEN_PATTERN = re.compile(
    r"(?i)(authorization|api[_-]?key|password|cst|x-security-token)\s*[:=]\s*[^\s,;]+"
)


def redact_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, item in value.items():
        if key.lower() in SENSITIVE_KEYS:
            redacted[key] = "[REDACTED]"
        elif isinstance(item, Mapping):
            redacted[key] = redact_mapping(item)
        else:
            redacted[key] = item
    return redacted


def redact_text(value: str) -> str:
    return TOKEN_PATTERN.sub(lambda match: f"{match.group(1)}=[REDACTED]", value)
