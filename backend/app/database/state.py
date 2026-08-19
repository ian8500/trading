from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.database.models import SystemStateRecord


def read_state(session: Session, key: str, default: dict[str, Any]) -> dict[str, Any]:
    record = session.get(SystemStateRecord, key)
    return dict(record.value) if record is not None else dict(default)


def write_state(session: Session, key: str, value: dict[str, Any]) -> dict[str, Any]:
    record = session.get(SystemStateRecord, key)
    if record is None:
        record = SystemStateRecord(key=key, value=value, updated_at=datetime.now(UTC))
        session.add(record)
    else:
        record.value = value
        record.updated_at = datetime.now(UTC)
    session.commit()
    return dict(value)
