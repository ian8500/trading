"""Canonical fingerprints for reproducible historical research runs."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Set
from dataclasses import fields, is_dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

SIMULATOR_BEHAVIOR_VERSION = "historical-simulator-v4-modeled-open-fx"


def _type_name(value: object) -> str:
    value_type = type(value)
    return f"{value_type.__module__}.{value_type.__qualname__}"


def canonicalize(value: Any, *, _stack: frozenset[int] = frozenset()) -> Any:
    """Convert domain state to stable JSON-compatible primitives.

    Unlike ``repr``, this never embeds memory addresses. Mapping and set order
    cannot affect the result, and financially important Decimal values retain
    their exact textual representation.
    """

    if isinstance(value, Enum):
        return {"__enum__": _type_name(value), "value": canonicalize(value.value)}
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, Decimal):
        return {"__decimal__": str(value)}
    if isinstance(value, float):
        return {"__float__": value.hex()}
    if isinstance(value, datetime):
        return {"__datetime__": value.isoformat()}
    if isinstance(value, date):
        return {"__date__": value.isoformat()}
    if isinstance(value, timedelta):
        return {
            "__timedelta__": {
                "days": value.days,
                "seconds": value.seconds,
                "microseconds": value.microseconds,
            }
        }
    if isinstance(value, Path):
        return {"__path__": str(value)}

    identity = id(value)
    if identity in _stack:
        return {"__cycle__": _type_name(value)}
    child_stack = _stack | {identity}

    if is_dataclass(value) and not isinstance(value, type):
        return {
            "__dataclass__": _type_name(value),
            "fields": {
                field.name: canonicalize(getattr(value, field.name), _stack=child_stack)
                for field in fields(value)
            },
        }
    if isinstance(value, Mapping):
        pairs = [
            (
                canonicalize(key, _stack=child_stack),
                canonicalize(item, _stack=child_stack),
            )
            for key, item in value.items()
        ]
        pairs.sort(key=lambda pair: json.dumps(pair[0], sort_keys=True, separators=(",", ":")))
        return {"__mapping__": pairs}
    if isinstance(value, Set) and not isinstance(value, str):
        items = [canonicalize(item, _stack=child_stack) for item in value]
        items.sort(key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")))
        return {"__set__": items}
    if isinstance(value, (list, tuple)):
        return {
            "__sequence_type__": _type_name(value),
            "items": [canonicalize(item, _stack=child_stack) for item in value],
        }

    state: dict[str, Any] = {}
    try:
        attributes = vars(value)
    except TypeError:
        attributes = {}
    for name, item in attributes.items():
        if not name.startswith("_"):
            state[name] = canonicalize(item, _stack=child_stack)
    return {"__object__": _type_name(value), "state": state}


def research_fingerprint(payload: Any, *, schema_version: int = 2) -> str:
    canonical = canonicalize(
        {
            "fingerprint_schema_version": schema_version,
            "payload": payload,
        }
    )
    encoded = json.dumps(
        canonical,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
