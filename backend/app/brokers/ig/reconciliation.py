"""Fail-closed comparison of IG Demo and durable internal order state."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import IGReconciliationError
from .orders import IGOrdersService, IntentStatus, SQLiteOrderIntentStore
from .positions import IGPositionsService
from .safety import PersistentDemoSafetyService


@dataclass(frozen=True, slots=True)
class IGReconciliationReport:
    complete: bool
    broker_position_count: int
    internal_open_count: int
    matched_deal_ids: tuple[str, ...]
    unknown_broker_deal_ids: tuple[str, ...]
    missing_broker_deal_ids: tuple[str, ...]
    unresolved_intent_ids: tuple[str, ...]
    unknown_working_order_ids: tuple[str, ...]


class IGReconciliationService:
    def __init__(
        self,
        positions: IGPositionsService,
        store: SQLiteOrderIntentStore,
        safety: PersistentDemoSafetyService,
        *,
        orders: IGOrdersService | None = None,
    ) -> None:
        self.positions = positions
        self.store = store
        self.safety = safety
        self.orders = orders

    async def reconcile(self) -> IGReconciliationReport:
        # Block immediately so concurrent workflows cannot open a new position
        # while broker state is being compared.
        self.safety.record_reconciliation(False, reason="RECONCILIATION_IN_PROGRESS")
        try:
            records = self.store.list()
            if self.orders is not None:
                for record in records:
                    if record.status in {
                        IntentStatus.PENDING_SUBMISSION,
                        IntentStatus.ACKNOWLEDGED,
                        IntentStatus.AMBIGUOUS,
                    }:
                        await self.orders.resolve(record)
                records = self.store.list()
            broker_positions = await self.positions.list()
            working_orders = await self.positions.pending_orders()
        except Exception as exc:
            self.safety.trip("RECONCILIATION_FAILED")
            raise IGReconciliationError("IG Demo reconciliation failed") from exc

        open_states = {IntentStatus.ACCEPTED, IntentStatus.PROTECTION_FAILED}
        internal_open = tuple(record for record in records if record.status in open_states)
        relevant_states = open_states | {
            IntentStatus.PENDING_SUBMISSION,
            IntentStatus.ACKNOWLEDGED,
            IntentStatus.AMBIGUOUS,
        }
        unresolved = tuple(
            sorted(
                record.intent_id
                for record in records
                if record.status in relevant_states
                and (record.status not in open_states or record.deal_id is None)
            )
        )
        relevant_records = tuple(record for record in records if record.status in relevant_states)
        by_id = {record.deal_id: record for record in relevant_records if record.deal_id}
        by_reference = {record.deal_reference: record for record in relevant_records}
        broker_by_id = {position.deal_id: position for position in broker_positions}

        matched = tuple(
            sorted(
                position.deal_id
                for position in broker_positions
                if position.deal_id in by_id
                or (position.deal_reference is not None and position.deal_reference in by_reference)
            )
        )
        unknown = tuple(
            sorted(
                position.deal_id
                for position in broker_positions
                if position.deal_id not in by_id
                and (position.deal_reference is None or position.deal_reference not in by_reference)
            )
        )
        missing = tuple(
            sorted(
                record.deal_id
                for record in internal_open
                if record.deal_id is not None and record.deal_id not in broker_by_id
            )
        )
        # This V1 integration creates immediate positions only.  Any open
        # broker working order is therefore external/unknown.
        unknown_working = tuple(sorted(order.deal_id for order in working_orders))
        complete = not (unknown or missing or unresolved or unknown_working)
        report = IGReconciliationReport(
            complete=complete,
            broker_position_count=len(broker_positions),
            internal_open_count=len(internal_open),
            matched_deal_ids=matched,
            unknown_broker_deal_ids=unknown,
            missing_broker_deal_ids=missing,
            unresolved_intent_ids=unresolved,
            unknown_working_order_ids=unknown_working,
        )
        if complete:
            self.safety.record_reconciliation(True)
        else:
            self.safety.trip("RECONCILIATION_REQUIRED")
        return report
