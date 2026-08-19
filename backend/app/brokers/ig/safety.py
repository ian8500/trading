"""Persistent fail-closed controls for autonomous IG Demo execution."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .errors import IGConfigurationError, IGOrderSafetyError


@dataclass(frozen=True, slots=True)
class DemoSafetyState:
    automation_enabled: bool
    new_trades_blocked: bool
    reconciliation_complete: bool
    block_reason: str | None
    critical_reasons: tuple[str, ...]
    updated_at: datetime


class PersistentDemoSafetyService:
    """Durable kill switch and manual-resume gate.

    Opening an existing store defaults to disabling automation and requiring a
    fresh reconciliation.  This prevents a process restart from silently
    resuming order flow.
    """

    def __init__(self, database_path: str | Path, *, resume_on_restart: bool = False) -> None:
        self.database_path = Path(database_path)
        if str(database_path) == ":memory:":
            raise IGConfigurationError("the IG safety store must be persistent")
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialise(resume_on_restart=resume_on_restart)
        try:
            os.chmod(self.database_path, 0o600)
        except OSError as exc:
            raise IGOrderSafetyError("IG safety store permissions could not be secured") from exc

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialise(self, *, resume_on_restart: bool) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS ig_demo_safety_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    automation_enabled INTEGER NOT NULL,
                    new_trades_blocked INTEGER NOT NULL,
                    reconciliation_complete INTEGER NOT NULL,
                    block_reason TEXT,
                    critical_reasons TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            row = connection.execute("SELECT id FROM ig_demo_safety_state WHERE id = 1").fetchone()
            now = datetime.now(UTC).isoformat()
            if row is None:
                connection.execute(
                    "INSERT INTO ig_demo_safety_state VALUES (1, 0, 1, 0, ?, '[]', ?)",
                    ("MANUAL_START_REQUIRED", now),
                )
            elif not resume_on_restart:
                connection.execute(
                    """
                    UPDATE ig_demo_safety_state
                    SET automation_enabled = 0,
                        new_trades_blocked = 1,
                        reconciliation_complete = 0,
                        block_reason = ?,
                        updated_at = ?
                    WHERE id = 1
                    """,
                    ("RESTART_RECONCILIATION_REQUIRED", now),
                )

    def state(self) -> DemoSafetyState:
        try:
            with self._lock, self._connect() as connection:
                row = connection.execute(
                    "SELECT * FROM ig_demo_safety_state WHERE id = 1"
                ).fetchone()
            if row is None:
                raise IGOrderSafetyError("IG safety state is unavailable")
            reasons = json.loads(row["critical_reasons"])
            if not isinstance(reasons, list) or not all(
                isinstance(reason, str) for reason in reasons
            ):
                raise IGOrderSafetyError("IG safety state is unavailable")
            return DemoSafetyState(
                automation_enabled=bool(row["automation_enabled"]),
                new_trades_blocked=bool(row["new_trades_blocked"]),
                reconciliation_complete=bool(row["reconciliation_complete"]),
                block_reason=row["block_reason"],
                critical_reasons=tuple(str(reason) for reason in reasons),
                updated_at=datetime.fromisoformat(row["updated_at"]),
            )
        except (sqlite3.Error, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise IGOrderSafetyError("IG safety state is unavailable") from exc

    def _update(self, **changes: object) -> DemoSafetyState:
        allowed = {
            "automation_enabled",
            "new_trades_blocked",
            "reconciliation_complete",
            "block_reason",
            "critical_reasons",
        }
        if not changes or not set(changes).issubset(allowed):
            raise ValueError("invalid safety state update")
        encoded: dict[str, object] = {}
        for key, value in changes.items():
            if key in {"automation_enabled", "new_trades_blocked", "reconciliation_complete"}:
                encoded[key] = int(bool(value))
            elif key == "critical_reasons":
                if not isinstance(value, (tuple, list, set, frozenset)):
                    raise ValueError("critical reasons must be a collection")
                encoded[key] = json.dumps(sorted({str(item) for item in value}))
            else:
                encoded[key] = value
        encoded["updated_at"] = datetime.now(UTC).isoformat()
        assignments = ", ".join(f"{key} = ?" for key in encoded)
        try:
            with self._lock, self._connect() as connection:
                connection.execute(
                    f"UPDATE ig_demo_safety_state SET {assignments} WHERE id = 1",  # noqa: S608 - fixed keys
                    tuple(encoded.values()),
                )
        except sqlite3.Error as exc:
            raise IGOrderSafetyError("IG safety state could not be persisted") from exc
        return self.state()

    def record_reconciliation(
        self, complete: bool, *, reason: str | None = None
    ) -> DemoSafetyState:
        if complete:
            return self._update(reconciliation_complete=True)
        return self._update(
            reconciliation_complete=False,
            automation_enabled=False,
            new_trades_blocked=True,
            block_reason=reason or "RECONCILIATION_REQUIRED",
        )

    def start_autonomous_demo(self) -> DemoSafetyState:
        state = self.state()
        if state.critical_reasons:
            raise IGOrderSafetyError("critical IG Demo circuit breaker requires acknowledgement")
        if not state.reconciliation_complete:
            raise IGOrderSafetyError("IG Demo reconciliation is required before start")
        return self._update(automation_enabled=True, new_trades_blocked=False, block_reason=None)

    def stop_new_trades(self, reason: str = "MANUAL_STOP") -> DemoSafetyState:
        return self._update(automation_enabled=False, new_trades_blocked=True, block_reason=reason)

    def trip(self, reason: str) -> DemoSafetyState:
        cleaned = (
            "".join(ch for ch in reason.upper() if ch.isalnum() or ch == "_")[:80] or "UNKNOWN"
        )
        state = self.state()
        return self._update(
            automation_enabled=False,
            new_trades_blocked=True,
            reconciliation_complete=False,
            block_reason=cleaned,
            critical_reasons=(*state.critical_reasons, cleaned),
        )

    def acknowledge_circuit_breakers(self) -> DemoSafetyState:
        """Manual acknowledgement clears reasons but never starts automation."""

        return self._update(
            automation_enabled=False,
            new_trades_blocked=True,
            reconciliation_complete=False,
            block_reason="RECONCILIATION_REQUIRED",
            critical_reasons=(),
        )

    def assert_new_orders_allowed(self) -> None:
        state = self.state()
        if (
            not state.automation_enabled
            or state.new_trades_blocked
            or not state.reconciliation_complete
            or state.critical_reasons
        ):
            raise IGOrderSafetyError("new IG Demo orders are blocked")
