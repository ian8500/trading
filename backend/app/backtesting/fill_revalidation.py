from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal

from app.core.clock import SimulationClock, ensure_utc
from app.instruments import Instrument
from app.portfolio import ManagedCapitalLedger, PortfolioRiskState
from app.risk import ApprovedOrder, RiskDecision, RiskEngine, RiskLimits, RiskTaper


@dataclass(frozen=True, slots=True)
class FillRiskRevalidation:
    """A fill-time sizing decision constrained by its causal reservation."""

    approval_decision: RiskDecision
    fill_decision: RiskDecision
    fill_order: ApprovedOrder | None
    reservation_breaches: tuple[str, ...]

    @property
    def approved(self) -> bool:
        return self.fill_order is not None

    def audit_details(self) -> dict[str, object]:
        return {
            "approved": self.approved,
            "approval_decision": _decision_details(self.approval_decision),
            "revalidated_decision": _decision_details(self.fill_decision),
            "reservation_breaches": list(self.reservation_breaches),
        }


@dataclass(frozen=True, slots=True)
class FillRiskRevalidationPolicy:
    """Re-price an approved reservation without reading later completion state.

    Portfolio bars are processed at completion even though an order fills at
    the modeled open.  Current ledger/position state can therefore contain
    events later than the fill instant.  Revalidation deliberately uses the
    original approved equity/risk reservation and permits only an equal or
    smaller size, risk, notional and margin.  Other open/pending exposure was
    already included when that reservation was approved, so replacing it with
    no more than its reserved amounts cannot increase portfolio risk.
    """

    policy_id: str = "fill-risk-revalidation-v1-reservation-capped"

    def evaluate(
        self,
        order: ApprovedOrder,
        instrument: Instrument,
        *,
        starting_capital: Decimal,
        entry_price: Decimal,
        entry_conversion: Decimal,
        entry_at: datetime,
        risk_limits: RiskLimits,
        risk_taper: RiskTaper | None,
    ) -> FillRiskRevalidation:
        approval = order.decision
        timestamp = ensure_utc(entry_at)
        maximum_size = approval.position_size
        if instrument.max_deal_size is not None:
            maximum_size = min(maximum_size, instrument.max_deal_size)
        fill_instrument = replace(
            instrument,
            currency_conversion=entry_conversion,
            max_deal_size=maximum_size,
        )
        fill_candidate = replace(
            order.candidate,
            timestamp=timestamp,
            signal_price=entry_price,
            proposed_stop_distance=order.stop_distance,
            proposed_target_distance=order.target_distance,
        )
        # An isolated gate prevents completion-time breaker/ledger state from
        # leaking backwards into the modeled-open decision.
        fill_engine = RiskEngine(
            risk_limits,
            clock=SimulationClock(timestamp),
            risk_taper=risk_taper,
        )
        approval_ledger = ManagedCapitalLedger(starting_capital)
        decision = fill_engine.evaluate(
            fill_candidate,
            fill_instrument,
            approval_ledger,
            PortfolioRiskState(peak_equity=approval.equity_basis),
            now=timestamp,
            managed_equity=approval.equity_basis,
        )
        timing_breaches = (
            (
                (
                    f"modeled fill {timestamp.isoformat()} precedes approval signal "
                    f"{order.candidate.timestamp.isoformat()}"
                ),
            )
            if timestamp < order.candidate.timestamp
            else ()
        )
        breaches = (*timing_breaches, *_reservation_breaches(approval, decision))
        fill_order = None
        if decision.approved and not breaches:
            fill_order = ApprovedOrder(
                fill_candidate,
                decision,
                order.stop_distance,
                order.target_distance,
            )
        return FillRiskRevalidation(approval, decision, fill_order, breaches)

    def audit_details(self) -> dict[str, object]:
        return {
            "policy_id": self.policy_id,
            "sizing_state_basis": "original causal approval reservation",
            "completion_state_used": False,
            "minimum_fill_time": "original approval signal timestamp",
            "maximum_fill_size": "approval position size",
            "maximum_fill_risk": "approval planned monetary risk",
            "maximum_fill_notional": "approval notional",
            "maximum_fill_margin": "approval margin",
            "breach_action": "reject fill",
        }


def _reservation_breaches(
    approval: RiskDecision,
    fill: RiskDecision,
) -> tuple[str, ...]:
    if not fill.approved:
        return ()
    comparisons = (
        ("position size", fill.position_size, approval.position_size),
        ("planned monetary risk", fill.planned_monetary_risk, approval.planned_monetary_risk),
        ("notional", fill.notional, approval.notional),
        ("margin", fill.margin_required, approval.margin_required),
    )
    return tuple(
        f"fill {label} {actual} exceeds approved reservation {reserved}"
        for label, actual, reserved in comparisons
        if actual > reserved
    )


def _decision_details(decision: RiskDecision) -> dict[str, object]:
    return {
        "approved": decision.approved,
        "decision_id": decision.decision_id,
        "reasons": list(decision.reasons),
        "equity_basis": str(decision.equity_basis),
        "risk_fraction": str(decision.risk_fraction),
        "permitted_risk": str(decision.permitted_risk),
        "position_size": str(decision.position_size),
        "planned_monetary_risk": str(decision.planned_monetary_risk),
        "notional": str(decision.notional),
        "margin_required": str(decision.margin_required),
    }
