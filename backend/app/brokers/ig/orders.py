"""Idempotent IG Demo order intent and protective-stop workflow."""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import threading
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any, ClassVar

from ..base import BrokerOrderResult, BrokerOrderStatus, BrokerPosition, Direction
from .capabilities import IGCapabilityDiscovery
from .client import IGClient
from .confirmations import IGConfirmation, IGConfirmationsService
from .errors import (
    IGAPIError,
    IGAuthenticationError,
    IGConfigurationError,
    IGOrderSafetyError,
    IGTransportError,
)
from .positions import IGPositionsService
from .prices import IGPricesService
from .safety import PersistentDemoSafetyService
from .utils import require_deal_id, require_deal_reference, require_epic

_LOG = logging.getLogger(__name__)
_EXPIRY = re.compile(r"^(?:\d{2}-)?[A-Z]{3}-\d{2}$|^-$|^DFB$")


def _utcnow() -> datetime:
    return datetime.now(UTC)


def new_intent_id() -> str:
    # The IG dealReference constraint is 1-30 ASCII letters/digits/_/-.  The
    # full 128-bit UUID is preserved by encoding it in URL-safe base64-like
    # alphabet would add complexity; 120 random bits still gives ample entropy.
    return uuid.uuid4().hex[:30]


class IntentStatus(StrEnum):
    PENDING_SUBMISSION = "PENDING_SUBMISSION"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    AMBIGUOUS = "AMBIGUOUS"
    PROTECTION_FAILED = "PROTECTION_FAILED"
    CLOSED_FOR_SAFETY = "CLOSED_FOR_SAFETY"


@dataclass(frozen=True, slots=True)
class IGOrderIntent:
    epic: str
    direction: Direction
    size: Decimal
    currency_code: str
    risk_approval_id: str
    risk_approved: bool
    expiry: str = "-"
    order_type: str = "MARKET"
    level: Decimal | None = None
    stop_distance: Decimal | None = None
    stop_level: Decimal | None = None
    limit_distance: Decimal | None = None
    limit_level: Decimal | None = None
    guaranteed_stop: bool = False
    force_open: bool = True
    protective_stop_required: bool = True
    intent_id: str = field(default_factory=new_intent_id)

    def __post_init__(self) -> None:
        require_epic(self.epic)
        require_deal_reference(self.intent_id)
        if not self.size.is_finite() or self.size <= 0:
            raise IGOrderSafetyError("IG Demo order size must be positive")
        size_exponent = self.size.as_tuple().exponent
        if isinstance(size_exponent, int) and size_exponent < -12:
            raise IGOrderSafetyError("IG Demo order size has more than 12 decimal places")
        if (
            len(self.currency_code) != 3
            or not self.currency_code.isalpha()
            or not self.currency_code.isupper()
        ):
            raise IGOrderSafetyError("IG Demo order currency must be a three-letter code")
        if not self.risk_approval_id or len(self.risk_approval_id) > 100:
            raise IGOrderSafetyError("a persisted RiskEngine approval identifier is required")
        if not _EXPIRY.fullmatch(self.expiry):
            raise IGOrderSafetyError("invalid IG expiry")
        if self.order_type not in {"MARKET", "LIMIT"}:
            raise IGOrderSafetyError("unsupported IG Demo immediate order type")
        if self.order_type == "MARKET" and self.level is not None:
            raise IGOrderSafetyError("market orders cannot specify a level")
        if self.order_type == "LIMIT" and self.level is None:
            raise IGOrderSafetyError("limit fill-or-kill orders require a level")
        for name, value in (
            ("level", self.level),
            ("stop distance", self.stop_distance),
            ("stop level", self.stop_level),
            ("limit distance", self.limit_distance),
            ("limit level", self.limit_level),
        ):
            if value is not None and (not value.is_finite() or value <= 0):
                raise IGOrderSafetyError(f"IG Demo order {name} must be positive and finite")
        if self.stop_distance is not None and self.stop_level is not None:
            raise IGOrderSafetyError("set only one of stop distance or stop level")
        if self.limit_distance is not None and self.limit_level is not None:
            raise IGOrderSafetyError("set only one of limit distance or limit level")
        if self.protective_stop_required and self.stop_distance is None and self.stop_level is None:
            raise IGOrderSafetyError("a protective stop is mandatory")
        if self.guaranteed_stop and self.stop_distance is None and self.stop_level is None:
            raise IGOrderSafetyError("a guaranteed stop requires a stop distance or level")
        if not self.force_open and any(
            value is not None
            for value in (
                self.stop_distance,
                self.stop_level,
                self.limit_distance,
                self.limit_level,
            )
        ):
            raise IGOrderSafetyError("attached protection requires forceOpen")

    def persisted_payload(self) -> dict[str, Any]:
        return {
            "epic": self.epic,
            "direction": self.direction.value,
            "size": str(self.size),
            "currency_code": self.currency_code,
            "risk_approval_id": self.risk_approval_id,
            "risk_approved": self.risk_approved,
            "expiry": self.expiry,
            "order_type": self.order_type,
            "level": str(self.level) if self.level is not None else None,
            "stop_distance": str(self.stop_distance) if self.stop_distance is not None else None,
            "stop_level": str(self.stop_level) if self.stop_level is not None else None,
            "limit_distance": str(self.limit_distance) if self.limit_distance is not None else None,
            "limit_level": str(self.limit_level) if self.limit_level is not None else None,
            "guaranteed_stop": self.guaranteed_stop,
            "force_open": self.force_open,
            "protective_stop_required": self.protective_stop_required,
            "intent_id": self.intent_id,
        }


@dataclass(frozen=True, slots=True)
class OrderIntentRecord:
    intent_id: str
    status: IntentStatus
    epic: str
    direction: Direction
    size: Decimal
    risk_approval_id: str
    deal_reference: str
    deal_id: str | None
    reason: str | None
    payload: Mapping[str, Any] = field(repr=False)
    created_at: datetime
    updated_at: datetime


class SQLiteOrderIntentStore:
    """Durable order state written before the first broker submission."""

    _TRANSITIONS: ClassVar[dict[IntentStatus, set[IntentStatus]]] = {
        IntentStatus.PENDING_SUBMISSION: {
            IntentStatus.ACKNOWLEDGED,
            IntentStatus.ACCEPTED,
            IntentStatus.REJECTED,
            IntentStatus.AMBIGUOUS,
            IntentStatus.PROTECTION_FAILED,
        },
        IntentStatus.ACKNOWLEDGED: {
            IntentStatus.ACCEPTED,
            IntentStatus.REJECTED,
            IntentStatus.AMBIGUOUS,
            IntentStatus.PROTECTION_FAILED,
        },
        IntentStatus.AMBIGUOUS: {
            IntentStatus.ACCEPTED,
            IntentStatus.REJECTED,
            IntentStatus.PROTECTION_FAILED,
        },
        IntentStatus.ACCEPTED: {IntentStatus.PROTECTION_FAILED, IntentStatus.CLOSED_FOR_SAFETY},
        IntentStatus.PROTECTION_FAILED: {IntentStatus.CLOSED_FOR_SAFETY},
        IntentStatus.REJECTED: set(),
        IntentStatus.CLOSED_FOR_SAFETY: set(),
    }

    def __init__(self, database_path: str | Path) -> None:
        if str(database_path) == ":memory:":
            raise IGConfigurationError("the IG intent store must be persistent")
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS ig_order_intents (
                    intent_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    epic TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    size TEXT NOT NULL,
                    risk_approval_id TEXT NOT NULL,
                    deal_reference TEXT NOT NULL UNIQUE,
                    deal_id TEXT,
                    reason TEXT,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        try:
            os.chmod(self.database_path, 0o600)
        except OSError as exc:
            raise IGOrderSafetyError(
                "IG order intent store permissions could not be secured"
            ) from exc

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        return connection

    def create_pending(self, intent: IGOrderIntent) -> OrderIntentRecord:
        record, _ = self.claim_pending(intent)
        return record

    def claim_pending(self, intent: IGOrderIntent) -> tuple[OrderIntentRecord, bool]:
        """Atomically claim the one permitted submission for an intent ID."""

        now = datetime.now(UTC).isoformat()
        created = False
        try:
            with self._lock, self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO ig_order_intents
                    (intent_id, status, epic, direction, size, risk_approval_id,
                     deal_reference, deal_id, reason, payload_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?)
                    """,
                    (
                        intent.intent_id,
                        IntentStatus.PENDING_SUBMISSION.value,
                        intent.epic,
                        intent.direction.value,
                        str(intent.size),
                        intent.risk_approval_id,
                        intent.intent_id,
                        json.dumps(intent.persisted_payload(), sort_keys=True),
                        now,
                        now,
                    ),
                )
                created = True
        except sqlite3.IntegrityError as exc:
            existing = self.get(intent.intent_id)
            if existing is not None:
                return existing, False
            raise IGOrderSafetyError("IG order intent could not be persisted") from exc
        except sqlite3.Error as exc:
            raise IGOrderSafetyError("IG order intent could not be persisted") from exc
        record = self.get(intent.intent_id)
        if record is None:  # pragma: no cover - defensive
            raise IGOrderSafetyError("IG order intent persistence verification failed")
        return record, created

    def get(self, intent_id: str) -> OrderIntentRecord | None:
        try:
            with self._lock, self._connect() as connection:
                row = connection.execute(
                    "SELECT * FROM ig_order_intents WHERE intent_id = ?", (intent_id,)
                ).fetchone()
        except sqlite3.Error as exc:
            raise IGOrderSafetyError("IG order intent store is unavailable") from exc
        return self._parse(row) if row is not None else None

    def list(self) -> tuple[OrderIntentRecord, ...]:
        try:
            with self._lock, self._connect() as connection:
                rows = connection.execute(
                    "SELECT * FROM ig_order_intents ORDER BY created_at"
                ).fetchall()
        except sqlite3.Error as exc:
            raise IGOrderSafetyError("IG order intent store is unavailable") from exc
        return tuple(self._parse(row) for row in rows)

    def transition(
        self,
        intent_id: str,
        status: IntentStatus,
        *,
        deal_id: str | None = None,
        reason: str | None = None,
    ) -> OrderIntentRecord:
        with self._lock:
            current = self.get(intent_id)
            if current is None:
                raise IGOrderSafetyError("unknown IG order intent")
            if status != current.status and status not in self._TRANSITIONS[current.status]:
                raise IGOrderSafetyError(
                    f"invalid IG intent transition {current.status} -> {status}"
                )
            now = datetime.now(UTC).isoformat()
            try:
                with self._connect() as connection:
                    connection.execute(
                        """
                        UPDATE ig_order_intents
                        SET status = ?, deal_id = COALESCE(?, deal_id), reason = ?, updated_at = ?
                        WHERE intent_id = ?
                        """,
                        (status.value, deal_id, reason, now, intent_id),
                    )
            except sqlite3.Error as exc:
                raise IGOrderSafetyError(
                    "IG order intent transition could not be persisted"
                ) from exc
        result = self.get(intent_id)
        if result is None:  # pragma: no cover
            raise IGOrderSafetyError("IG order intent transition verification failed")
        return result

    @staticmethod
    def _parse(row: sqlite3.Row) -> OrderIntentRecord:
        try:
            payload = json.loads(row["payload_json"])
            return OrderIntentRecord(
                intent_id=row["intent_id"],
                status=IntentStatus(row["status"]),
                epic=row["epic"],
                direction=Direction(row["direction"]),
                size=Decimal(row["size"]),
                risk_approval_id=row["risk_approval_id"],
                deal_reference=row["deal_reference"],
                deal_id=row["deal_id"],
                reason=row["reason"],
                payload=payload,
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
            )
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise IGOrderSafetyError("IG order intent record is corrupt") from exc


class IGOrdersService:
    def __init__(
        self,
        client: IGClient,
        confirmations: IGConfirmationsService,
        positions: IGPositionsService,
        prices: IGPricesService,
        capabilities: IGCapabilityDiscovery,
        store: SQLiteOrderIntentStore,
        safety: PersistentDemoSafetyService,
        *,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self.client = client
        self.confirmations = confirmations
        self.positions = positions
        self.prices = prices
        self.capabilities = capabilities
        self.store = store
        self.safety = safety
        self._clock = clock

    async def submit(self, intent: IGOrderIntent) -> BrokerOrderResult:
        # The intent id is also IG's user-defined dealReference.  Any persisted
        # record means submission may already have reached IG: resolve only.
        existing = self.store.get(intent.intent_id)
        if existing is not None:
            self._verify_same_intent(existing, intent)
            try:
                return await self.resolve(existing, intent=intent)
            except Exception:
                if existing.status not in {
                    IntentStatus.ACCEPTED,
                    IntentStatus.REJECTED,
                    IntentStatus.CLOSED_FOR_SAFETY,
                }:
                    if existing.status != IntentStatus.AMBIGUOUS:
                        existing = self.store.transition(
                            existing.intent_id,
                            IntentStatus.AMBIGUOUS,
                            reason="RECONCILIATION_UNAVAILABLE",
                        )
                    self.safety.trip("AMBIGUOUS_ORDER_STATUS")
                return self._result(existing)

        self.safety.assert_new_orders_allowed()
        await self._preflight(intent)
        record, claimed = self.store.claim_pending(intent)
        self._verify_same_intent(record, intent)
        if not claimed:
            # Another worker won the atomic claim.  Its POST may be in flight;
            # this worker is restricted to confirmation/position lookup.
            try:
                result = await self.resolve(record, intent=intent)
            except Exception:
                if record.status != IntentStatus.AMBIGUOUS:
                    record = self.store.transition(
                        record.intent_id,
                        IntentStatus.AMBIGUOUS,
                        reason="CONCURRENT_SUBMISSION_UNRESOLVED",
                    )
                self.safety.trip("AMBIGUOUS_ORDER_STATUS")
                return self._result(record)
            if result.status == BrokerOrderStatus.AMBIGUOUS:
                self.safety.trip("AMBIGUOUS_ORDER_STATUS")
            return result
        body = self._request_body(intent)
        try:
            payload = await self.client.request(
                "POST",
                "/positions/otc",
                version=2,
                json_body=body,
                allow_auth_retry=False,
            )
        except IGAPIError as exc:
            if exc.status_code < 500 and exc.status_code not in {408}:
                record = self.store.transition(
                    intent.intent_id, IntentStatus.REJECTED, reason=exc.error_code
                )
                return self._result(record)
            return await self._mark_and_resolve_ambiguous(record, intent, "HTTP_RESPONSE_AMBIGUOUS")
        except (IGTransportError, IGAuthenticationError):
            return await self._mark_and_resolve_ambiguous(record, intent, "TRANSPORT_AMBIGUOUS")
        except Exception:
            return await self._mark_and_resolve_ambiguous(
                record, intent, "UNEXPECTED_SUBMISSION_FAILURE"
            )

        if not isinstance(payload, Mapping) or not isinstance(payload.get("dealReference"), str):
            return await self._mark_and_resolve_ambiguous(record, intent, "ACKNOWLEDGEMENT_MISSING")
        deal_reference = payload["dealReference"]
        if deal_reference != intent.intent_id:
            return await self._mark_and_resolve_ambiguous(record, intent, "DEAL_REFERENCE_MISMATCH")
        record = self.store.transition(intent.intent_id, IntentStatus.ACKNOWLEDGED)
        try:
            confirmation = await self.confirmations.wait_for(deal_reference)
        except Exception:
            return await self._mark_and_resolve_ambiguous(
                record, intent, "CONFIRMATION_UNAVAILABLE"
            )
        if confirmation is None:
            return await self._mark_and_resolve_ambiguous(record, intent, "CONFIRMATION_DELAYED")
        return await self._handle_confirmation(record, intent, confirmation)

    async def _preflight(self, intent: IGOrderIntent) -> None:
        if not intent.risk_approved:
            raise IGOrderSafetyError("RiskEngine did not approve this IG Demo intent")
        capability = await self.capabilities.discover(intent.epic)
        if not capability.tradeable:
            raise IGOrderSafetyError("IG Demo market is not TRADEABLE")
        if intent.order_type == "MARKET" and capability.market_order_supported is not True:
            raise IGOrderSafetyError("market orders are not confirmed for this IG Demo market")
        if intent.force_open and capability.force_open_supported is not True:
            raise IGOrderSafetyError("force-open is not confirmed for this IG Demo market")
        has_attached_levels = any(
            value is not None
            for value in (
                intent.stop_distance,
                intent.stop_level,
                intent.limit_distance,
                intent.limit_level,
            )
        )
        if has_attached_levels and capability.stops_limits_supported is not True:
            raise IGOrderSafetyError("attached stops are not confirmed for this IG Demo market")
        if capability.currency is None or intent.currency_code != capability.currency:
            raise IGOrderSafetyError("IG Demo order currency does not match the market")
        if capability.expiry is None or intent.expiry != capability.expiry:
            raise IGOrderSafetyError("IG Demo order expiry does not match the market")
        if capability.minimum_deal_size is None or intent.size < capability.minimum_deal_size:
            raise IGOrderSafetyError("IG Demo order is below the discovered minimum deal size")
        if capability.raw_rule_units.get("minDealSize") != "POINTS":
            raise IGOrderSafetyError("IG Demo minimum deal-size unit is unsupported")
        if capability.maximum_deal_size is not None and intent.size > capability.maximum_deal_size:
            raise IGOrderSafetyError("IG Demo order exceeds the discovered maximum deal size")
        if (
            capability.maximum_deal_size is not None
            and capability.raw_rule_units.get("maxDealSize") != "POINTS"
        ):
            raise IGOrderSafetyError("IG Demo maximum deal-size unit is unsupported")
        if intent.guaranteed_stop and not capability.guaranteed_stop_supported:
            raise IGOrderSafetyError("guaranteed stops are unavailable for this IG Demo market")
        minimum_stop = (
            capability.minimum_guaranteed_stop_distance
            if intent.guaranteed_stop
            else capability.minimum_stop_distance
        )
        minimum_stop_rule = (
            "minControlledRiskStopDistance"
            if intent.guaranteed_stop
            else "minNormalStopOrLimitDistance"
        )
        quote = await self.prices.snapshot(intent.epic)
        now = self._clock()
        if now.tzinfo is None:
            raise IGOrderSafetyError("order clock must be timezone-aware")
        age = now.astimezone(UTC) - quote.timestamp.astimezone(UTC)
        maximum_age = timedelta(seconds=self.client.config.maximum_quote_age_seconds)
        if (
            quote.market_status != "TRADEABLE"
            or quote.delayed
            or age < timedelta(seconds=-1)
            or age > maximum_age
        ):
            raise IGOrderSafetyError("IG Demo price is stale, delayed, or not tradeable")

        reference_level = (
            intent.level
            if intent.order_type == "LIMIT" and intent.level is not None
            else (quote.ask if intent.direction == Direction.BUY else quote.bid)
        )
        actual_stop_distance = intent.stop_distance
        if intent.stop_level is not None:
            if intent.direction == Direction.BUY:
                if intent.stop_level >= reference_level:
                    raise IGOrderSafetyError("buy protective stop must be below the entry level")
                actual_stop_distance = reference_level - intent.stop_level
            else:
                if intent.stop_level <= reference_level:
                    raise IGOrderSafetyError("sell protective stop must be above the entry level")
                actual_stop_distance = intent.stop_level - reference_level
        if actual_stop_distance is not None:
            if minimum_stop is None:
                raise IGOrderSafetyError("IG Demo minimum stop distance is unavailable")
            minimum = self._absolute_rule_distance(
                minimum_stop,
                capability.raw_rule_units.get(minimum_stop_rule),
                quote.midpoint,
                minimum_stop_rule,
            )
            if actual_stop_distance < minimum:
                raise IGOrderSafetyError("protective stop violates the IG minimum distance")

        actual_limit_distance = intent.limit_distance
        if intent.limit_level is not None:
            if intent.direction == Direction.BUY:
                if intent.limit_level <= reference_level:
                    raise IGOrderSafetyError("buy limit target must be above the entry level")
                actual_limit_distance = intent.limit_level - reference_level
            else:
                if intent.limit_level >= reference_level:
                    raise IGOrderSafetyError("sell limit target must be below the entry level")
                actual_limit_distance = reference_level - intent.limit_level
        if actual_limit_distance is not None:
            if capability.minimum_limit_distance is None:
                raise IGOrderSafetyError("IG Demo minimum limit distance is unavailable")
            minimum_limit = self._absolute_rule_distance(
                capability.minimum_limit_distance,
                capability.raw_rule_units.get("minNormalStopOrLimitDistance"),
                quote.midpoint,
                "minNormalStopOrLimitDistance",
            )
            if actual_limit_distance < minimum_limit:
                raise IGOrderSafetyError("limit target violates the IG minimum distance")

    @staticmethod
    def _absolute_rule_distance(
        value: Decimal,
        unit: str | None,
        midpoint: Decimal,
        rule_name: str,
    ) -> Decimal:
        if unit == "POINTS":
            return value
        if unit == "PERCENTAGE":
            return midpoint * value / Decimal("100")
        raise IGOrderSafetyError(f"IG Demo returned an unsupported unit for {rule_name}")

    def _verify_same_intent(self, record: OrderIntentRecord, intent: IGOrderIntent) -> None:
        if dict(record.payload) != intent.persisted_payload():
            self.safety.trip("INTENT_ID_CONFLICT")
            raise IGOrderSafetyError("IG order intent ID was reused with different parameters")

    @staticmethod
    def _request_body(intent: IGOrderIntent) -> dict[str, Any]:
        body: dict[str, Any] = {
            "currencyCode": intent.currency_code,
            "dealReference": intent.intent_id,
            "direction": intent.direction.value,
            "epic": intent.epic,
            "expiry": intent.expiry,
            "forceOpen": intent.force_open,
            "guaranteedStop": intent.guaranteed_stop,
            "orderType": intent.order_type,
            "size": float(intent.size),
            "timeInForce": "FILL_OR_KILL",
            "trailingStop": False,
        }
        for key, value in (
            ("level", intent.level),
            ("stopDistance", intent.stop_distance),
            ("stopLevel", intent.stop_level),
            ("limitDistance", intent.limit_distance),
            ("limitLevel", intent.limit_level),
        ):
            if value is not None:
                body[key] = float(value)
        return body

    async def _mark_and_resolve_ambiguous(
        self,
        record: OrderIntentRecord,
        intent: IGOrderIntent,
        reason: str,
    ) -> BrokerOrderResult:
        if record.status != IntentStatus.AMBIGUOUS:
            record = self.store.transition(record.intent_id, IntentStatus.AMBIGUOUS, reason=reason)
        try:
            result = await self.resolve(record, intent=intent)
        except Exception:
            self.safety.trip("AMBIGUOUS_ORDER_STATUS")
            return self._result(record)
        if result.status == BrokerOrderStatus.AMBIGUOUS:
            self.safety.trip("AMBIGUOUS_ORDER_STATUS")
        return result

    async def resolve(
        self,
        record: OrderIntentRecord,
        *,
        intent: IGOrderIntent | None = None,
    ) -> BrokerOrderResult:
        if record.status in {
            IntentStatus.REJECTED,
            IntentStatus.ACCEPTED,
            IntentStatus.CLOSED_FOR_SAFETY,
        }:
            return self._result(record)
        intent = intent or self._intent_from_record(record)
        confirmation = await self.confirmations.get(record.deal_reference)
        if confirmation is not None:
            return await self._handle_confirmation(record, intent, confirmation)
        matching = next(
            (
                position
                for position in await self.positions.list()
                if position.deal_reference == record.deal_reference
            ),
            None,
        )
        if matching is not None:
            if await self._ensure_protection(record, intent, matching, confirmation=None):
                updated = self.store.transition(
                    record.intent_id, IntentStatus.ACCEPTED, deal_id=matching.deal_id
                )
                return self._result(updated)
            return await self._protection_failure(record, intent, matching)
        current = self.store.get(record.intent_id) or record
        return BrokerOrderResult(
            intent_id=current.intent_id,
            status=BrokerOrderStatus.AMBIGUOUS,
            deal_reference=current.deal_reference,
            deal_id=current.deal_id,
            reason=current.reason or "UNRESOLVED",
        )

    async def _handle_confirmation(
        self,
        record: OrderIntentRecord,
        intent: IGOrderIntent,
        confirmation: IGConfirmation,
    ) -> BrokerOrderResult:
        invalid_confirmation = confirmation.deal_reference != record.deal_reference or (
            confirmation.epic is not None and confirmation.epic != intent.epic
        )
        if confirmation.deal_id is not None:
            try:
                require_deal_id(confirmation.deal_id)
            except IGConfigurationError:
                invalid_confirmation = True
        if invalid_confirmation:
            if record.status != IntentStatus.AMBIGUOUS:
                record = self.store.transition(
                    record.intent_id,
                    IntentStatus.AMBIGUOUS,
                    reason="CONFIRMATION_IDENTITY_MISMATCH",
                )
            self.safety.trip("AMBIGUOUS_ORDER_STATUS")
            return self._result(record, confirmation)
        if confirmation.deal_status not in {"ACCEPTED", "REJECTED"}:
            if record.status != IntentStatus.AMBIGUOUS:
                record = self.store.transition(
                    record.intent_id,
                    IntentStatus.AMBIGUOUS,
                    deal_id=confirmation.deal_id,
                    reason="INVALID_CONFIRMATION_STATUS",
                )
            self.safety.trip("AMBIGUOUS_ORDER_STATUS")
            return self._result(record, confirmation)
        if confirmation.deal_status == "REJECTED":
            updated = self.store.transition(
                record.intent_id,
                IntentStatus.REJECTED,
                deal_id=confirmation.deal_id,
                reason=confirmation.reason or "REJECTED",
            )
            return self._result(updated, confirmation)
        if not confirmation.deal_id:
            if record.status != IntentStatus.AMBIGUOUS:
                record = self.store.transition(
                    record.intent_id, IntentStatus.AMBIGUOUS, reason="CONFIRMATION_WITHOUT_DEAL_ID"
                )
            self.safety.trip("AMBIGUOUS_ORDER_STATUS")
            return self._result(record, confirmation)

        position = None
        try:
            position = await self.positions.get(confirmation.deal_id)
        except IGAPIError:
            # The confirmation itself can establish protection; a missing
            # immediate position read may simply be eventual consistency.
            position = None
        if await self._ensure_protection(record, intent, position, confirmation):
            updated = self.store.transition(
                record.intent_id, IntentStatus.ACCEPTED, deal_id=confirmation.deal_id
            )
            return self._result(updated, confirmation)
        return await self._protection_failure(record, intent, position, confirmation)

    async def _ensure_protection(
        self,
        record: OrderIntentRecord,
        intent: IGOrderIntent,
        position: BrokerPosition | None,
        confirmation: IGConfirmation | None,
    ) -> bool:
        if not intent.protective_stop_required:
            return True
        if confirmation is not None and (
            confirmation.stop_level is not None or confirmation.stop_distance is not None
        ):
            return True
        if position is not None and position.stop_level is not None:
            return True
        if position is None:
            return False

        stop_level = intent.stop_level
        if stop_level is None and intent.stop_distance is not None:
            stop_level = (
                position.level - intent.stop_distance
                if position.direction == Direction.BUY
                else position.level + intent.stop_distance
            )
        if stop_level is None:
            return False
        try:
            remediation_reference = await self.positions.update_protection(
                position.deal_id,
                stop_level=stop_level,
                guaranteed_stop=intent.guaranteed_stop or position.controlled_risk,
            )
            remediation = await self.confirmations.wait_for(remediation_reference)
            if remediation is None or not remediation.accepted:
                return False
            verified = await self.positions.get(position.deal_id)
            return verified is not None and verified.stop_level is not None
        except Exception:
            # A mutating protection request is never retried here.  The caller
            # immediately enters the close-and-suspend path.
            return False

    async def _protection_failure(
        self,
        record: OrderIntentRecord,
        intent: IGOrderIntent,
        position: BrokerPosition | None,
        confirmation: IGConfirmation | None = None,
    ) -> BrokerOrderResult:
        deal_id = (
            position.deal_id
            if position is not None
            else (confirmation.deal_id if confirmation else None)
        )
        current = self.store.get(record.intent_id) or record
        if current.status != IntentStatus.PROTECTION_FAILED:
            current = self.store.transition(
                record.intent_id,
                IntentStatus.PROTECTION_FAILED,
                deal_id=deal_id,
                reason="PROTECTIVE_STOP_UNCONFIRMED",
            )
        self.safety.trip("PROTECTIVE_STOP_FAILURE")
        if position is None and deal_id:
            try:
                position = await self.positions.get(deal_id)
            except Exception:
                position = None
        if position is not None:
            try:
                close_reference = await self.positions.close_position(position)
                close_confirmation = await self.confirmations.wait_for(close_reference)
                if close_confirmation is not None and close_confirmation.accepted:
                    current = self.store.transition(
                        current.intent_id,
                        IntentStatus.CLOSED_FOR_SAFETY,
                        deal_id=deal_id,
                        reason="CLOSED_AFTER_PROTECTIVE_STOP_FAILURE",
                    )
            except Exception:
                _LOG.critical("Emergency close after protective-stop failure was not confirmed")
        return BrokerOrderResult(
            intent_id=current.intent_id,
            status=BrokerOrderStatus.AMBIGUOUS,
            deal_reference=current.deal_reference,
            deal_id=current.deal_id,
            reason=current.reason,
            raw_confirmation=confirmation.raw if confirmation else None,
        )

    @staticmethod
    def _intent_from_record(record: OrderIntentRecord) -> IGOrderIntent:
        payload = record.payload

        def dec(name: str) -> Decimal | None:
            return Decimal(str(payload[name])) if payload.get(name) is not None else None

        return IGOrderIntent(
            epic=str(payload["epic"]),
            direction=Direction(str(payload["direction"])),
            size=Decimal(str(payload["size"])),
            currency_code=str(payload["currency_code"]),
            risk_approval_id=str(payload["risk_approval_id"]),
            risk_approved=bool(payload["risk_approved"]),
            expiry=str(payload.get("expiry") or "-"),
            order_type=str(payload.get("order_type") or "MARKET"),
            level=dec("level"),
            stop_distance=dec("stop_distance"),
            stop_level=dec("stop_level"),
            limit_distance=dec("limit_distance"),
            limit_level=dec("limit_level"),
            guaranteed_stop=bool(payload.get("guaranteed_stop")),
            force_open=bool(payload.get("force_open", True)),
            protective_stop_required=bool(payload.get("protective_stop_required", True)),
            intent_id=record.intent_id,
        )

    @staticmethod
    def _result(
        record: OrderIntentRecord,
        confirmation: IGConfirmation | None = None,
    ) -> BrokerOrderResult:
        status = {
            IntentStatus.ACCEPTED: BrokerOrderStatus.ACCEPTED,
            IntentStatus.REJECTED: BrokerOrderStatus.REJECTED,
            IntentStatus.PENDING_SUBMISSION: BrokerOrderStatus.PENDING,
            IntentStatus.ACKNOWLEDGED: BrokerOrderStatus.PENDING,
            IntentStatus.AMBIGUOUS: BrokerOrderStatus.AMBIGUOUS,
            IntentStatus.PROTECTION_FAILED: BrokerOrderStatus.AMBIGUOUS,
            IntentStatus.CLOSED_FOR_SAFETY: BrokerOrderStatus.REJECTED,
        }[record.status]
        return BrokerOrderResult(
            intent_id=record.intent_id,
            status=status,
            deal_reference=record.deal_reference,
            deal_id=record.deal_id,
            reason=record.reason,
            raw_confirmation=confirmation.raw if confirmation else None,
        )
