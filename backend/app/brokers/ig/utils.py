"""Parsing helpers shared by IG service modules."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import quote

from .errors import IGConfigurationError

_EPIC = re.compile(r"^[A-Za-z0-9._]{6,30}$")
_DEAL_ID = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
_ACCOUNT_ID = re.compile(r"^[A-Za-z0-9-]{1,30}$")
_DEAL_REFERENCE = re.compile(r"^[A-Za-z0-9_-]{1,30}$")


def decimal_or_none(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def mapping_or_empty(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def list_or_empty(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def require_epic(epic: str) -> str:
    if not _EPIC.fullmatch(epic):
        raise IGConfigurationError("invalid IG EPIC")
    return epic


def epic_path(epic: str) -> str:
    return quote(require_epic(epic), safe="._")


def require_deal_id(deal_id: str) -> str:
    if not _DEAL_ID.fullmatch(deal_id):
        raise IGConfigurationError("invalid IG deal identifier")
    return deal_id


def require_account_id(account_id: str) -> str:
    if not _ACCOUNT_ID.fullmatch(account_id):
        raise IGConfigurationError("invalid IG account identifier")
    return account_id


def require_deal_reference(deal_reference: str) -> str:
    if not _DEAL_REFERENCE.fullmatch(deal_reference):
        raise IGConfigurationError("invalid IG deal reference")
    return deal_reference


def parse_ig_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = value.strip()
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        parsed = None
    if parsed is None:
        for fmt in ("%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M:%S:%f", "%Y-%m-%d %H:%M:%S"):
            try:
                parsed = datetime.strptime(candidate, fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
