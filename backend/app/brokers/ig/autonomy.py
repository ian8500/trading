"""Server-side controls for starting, stopping, and emergency closing Demo."""

from __future__ import annotations

from dataclasses import dataclass

from .confirmations import IGConfirmationsService
from .positions import IGPositionsService
from .safety import DemoSafetyState, PersistentDemoSafetyService


@dataclass(frozen=True, slots=True)
class EmergencyCloseReport:
    attempted_deal_ids: tuple[str, ...]
    confirmed_closed_deal_ids: tuple[str, ...]
    unresolved_deal_ids: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return not self.unresolved_deal_ids


class IGDemoAutonomyService:
    def __init__(
        self,
        safety: PersistentDemoSafetyService,
        positions: IGPositionsService,
        confirmations: IGConfirmationsService,
    ) -> None:
        self.safety = safety
        self.positions = positions
        self.confirmations = confirmations

    def start(self) -> DemoSafetyState:
        return self.safety.start_autonomous_demo()

    def stop_new_trades(self) -> DemoSafetyState:
        return self.safety.stop_new_trades()

    async def emergency_close_all(self) -> EmergencyCloseReport:
        # Persist the kill switch before sending any close request.
        self.safety.stop_new_trades("EMERGENCY_CLOSE_IN_PROGRESS")
        positions = await self.positions.list()
        confirmed: list[str] = []
        unresolved: list[str] = []
        for position in positions:
            try:
                deal_reference = await self.positions.close_position(position)
                confirmation = await self.confirmations.wait_for(deal_reference)
                if confirmation is not None and confirmation.accepted:
                    confirmed.append(position.deal_id)
                else:
                    unresolved.append(position.deal_id)
            except Exception:
                unresolved.append(position.deal_id)
        if unresolved:
            self.safety.trip("EMERGENCY_CLOSE_INCOMPLETE")
        else:
            self.safety.stop_new_trades("EMERGENCY_CLOSE_COMPLETE")
        return EmergencyCloseReport(
            attempted_deal_ids=tuple(position.deal_id for position in positions),
            confirmed_closed_deal_ids=tuple(confirmed),
            unresolved_deal_ids=tuple(unresolved),
        )
