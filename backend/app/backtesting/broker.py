from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime
from decimal import Decimal

from app.backtesting.costs import CostModel, calculate_exit_costs, monetary_price_distance
from app.backtesting.models import Bar, ExitReason, Position, Trade
from app.core.clock import ensure_utc
from app.core.decimal import money
from app.instruments import Instrument
from app.portfolio import ManagedCapitalLedger
from app.risk import ApprovedOrder, RiskDecision


class BrokerBoundaryError(RuntimeError):
    pass


class HistoricalBroker:
    """Deterministic historical broker that only accepts risk capability objects."""

    def __init__(self, instrument: Instrument, cost_model: CostModel | None = None) -> None:
        self.instrument = instrument
        self.cost_model = cost_model or CostModel.from_preset("REALISTIC")
        self.submitted_order_count = 0
        self.fills: list[Position] = []

    def execute_order(
        self,
        order: ApprovedOrder,
        bar: Bar,
        *,
        entry_at: datetime | None = None,
        approval_signal_at: datetime | None = None,
        approval_decision: RiskDecision | None = None,
        approval_currency_conversion: Decimal | None = None,
        entry_currency_conversion: Decimal | None = None,
    ) -> Position:
        if not isinstance(order, ApprovedOrder) or not order.decision.approved:
            raise BrokerBoundaryError("orders must carry an approved RiskEngine decision")
        if order.candidate.instrument_id != self.instrument.id:
            raise BrokerBoundaryError("instrument mismatch")
        if bar.timestamp <= order.candidate.timestamp:
            raise BrokerBoundaryError("historical entry must occur after the signal bar")
        modeled_entry_at = ensure_utc(entry_at or bar.timestamp)
        original_signal_at = ensure_utc(approval_signal_at or order.candidate.timestamp)
        if modeled_entry_at < original_signal_at:
            raise BrokerBoundaryError("modeled entry cannot precede its approval signal")
        if modeled_entry_at < order.candidate.timestamp:
            raise BrokerBoundaryError("modeled entry cannot precede its signal")
        if modeled_entry_at > bar.timestamp:
            raise BrokerBoundaryError("modeled entry cannot follow bar completion")
        self.submitted_order_count += 1
        original_decision = approval_decision or order.decision
        approval_conversion = (
            self.instrument.currency_conversion
            if approval_currency_conversion is None
            else approval_currency_conversion
        )
        entry_conversion = (
            self.instrument.currency_conversion
            if entry_currency_conversion is None
            else entry_currency_conversion
        )
        entry_instrument = replace(
            self.instrument,
            currency_conversion=entry_conversion,
        )
        requested = bar.open
        half_spread = self.cost_model.half_spread_price(bar, requested)
        slippage = self.cost_model.slippage_price(requested)
        adverse = half_spread + slippage
        actual = requested + order.candidate.direction.multiplier * adverse
        stop = actual - order.candidate.direction.multiplier * order.stop_distance
        target = (
            None
            if order.target_distance is None
            else actual + order.candidate.direction.multiplier * order.target_distance
        )
        key = "|".join(
            (
                order.decision.decision_id,
                modeled_entry_at.isoformat(),
                bar.timestamp.isoformat(),
                self.instrument.id,
            )
        )
        entry_notional = money(
            requested
            * order.decision.position_size
            * entry_instrument.contract_size
            * entry_instrument.currency_conversion
        )
        entry_commission = money(
            entry_notional * self.cost_model.commission_bps_per_side / Decimal("10000")
        )
        # The simulator models ordinary stops. A guaranteed-stop premium must
        # only be charged by a future explicit guaranteed-stop order contract.
        entry_guaranteed_stop_premium = Decimal("0")
        entry_conversion_cost = money(
            entry_notional * self.cost_model.currency_conversion_bps / Decimal("10000")
        )
        position = Position(
            position_id=hashlib.sha256(key.encode()).hexdigest()[:24],
            instrument_id=self.instrument.id,
            strategy_version_id=order.candidate.strategy_version_id,
            direction=order.candidate.direction,
            quantity=order.decision.position_size,
            entry_timestamp=modeled_entry_at,
            requested_entry=requested,
            actual_entry=actual,
            stop_price=stop,
            target_price=target,
            entry_spread_cost=monetary_price_distance(
                half_spread, order.decision.position_size, entry_instrument
            ),
            entry_slippage_cost=monetary_price_distance(
                slippage, order.decision.position_size, entry_instrument
            ),
            planned_risk=order.decision.planned_monetary_risk,
            margin=order.decision.margin_required,
            regime=order.candidate.regime,
            candidate_score=order.candidate.score,
            risk_decision_id=original_decision.decision_id,
            fill_risk_decision_id=order.decision.decision_id,
            approval_planned_risk=original_decision.planned_monetary_risk,
            approval_notional=original_decision.notional,
            approval_margin=original_decision.margin_required,
            approval_currency_conversion=approval_conversion,
            entry_currency_conversion=entry_conversion,
            entry_notional=entry_notional,
            entry_commission=entry_commission,
            entry_guaranteed_stop_premium=entry_guaranteed_stop_premium,
            entry_currency_conversion_cost=entry_conversion_cost,
        )
        self.fills.append(position)
        return position

    def close_position(
        self,
        position: Position,
        requested_exit: Decimal,
        bar: Bar,
        reason: ExitReason,
        ledger: ManagedCapitalLedger,
        *,
        exit_currency_conversion: Decimal | None = None,
    ) -> Trade:
        exit_conversion = (
            self.instrument.currency_conversion
            if exit_currency_conversion is None
            else exit_currency_conversion
        )
        exit_instrument = replace(
            self.instrument,
            currency_conversion=exit_conversion,
        )
        half_spread = self.cost_model.half_spread_price(bar, requested_exit)
        slippage = self.cost_model.slippage_price(requested_exit)
        adverse = half_spread + slippage
        actual_exit = requested_exit - position.direction.multiplier * adverse
        holding_seconds = max(0, int((bar.timestamp - position.entry_timestamp).total_seconds()))
        gross = money(
            (requested_exit - position.requested_entry)
            * position.direction.multiplier
            * position.quantity
            * exit_instrument.point_value
            * exit_instrument.contract_size
            * exit_instrument.currency_conversion
        )
        costs = calculate_exit_costs(
            self.cost_model,
            position,
            bar,
            requested_exit,
            exit_instrument,
            holding_seconds,
        )
        before = ledger.equity
        trade_key = f"{position.position_id}|{bar.timestamp.isoformat()}|{reason.value}"
        trade_id = hashlib.sha256(trade_key.encode()).hexdigest()[:24]
        entry = ledger.post_trade(
            trade_id,
            gross,
            costs.total,
            timestamp=bar.timestamp,
            description=f"{position.direction.value} {position.instrument_id} {reason.value}",
        )
        return Trade(
            trade_id=trade_id,
            instrument_id=position.instrument_id,
            strategy_version_id=position.strategy_version_id,
            direction=position.direction,
            quantity=position.quantity,
            entry_timestamp=position.entry_timestamp,
            exit_timestamp=bar.timestamp,
            requested_entry=position.requested_entry,
            actual_entry=position.actual_entry,
            requested_exit=requested_exit,
            actual_exit=actual_exit,
            stop_price=position.stop_price,
            target_price=position.target_price,
            exit_reason=reason,
            gross_pnl=gross,
            spread_cost=costs.spread,
            slippage_cost=costs.slippage,
            financing_cost=costs.financing,
            commission=costs.commission,
            guaranteed_stop_premium=costs.guaranteed_stop_premium,
            currency_conversion_cost=costs.currency_conversion,
            total_cost=costs.total,
            net_pnl=entry.net_pnl,
            holding_seconds=holding_seconds,
            bars_held=position.bars_held,
            managed_equity_before=before,
            managed_equity_after=entry.equity_after,
            regime=position.regime,
            opportunity_score=position.candidate_score,
            risk_decision_id=position.risk_decision_id,
            fill_risk_decision_id=position.fill_risk_decision_id,
            approval_planned_risk=position.approval_planned_risk,
            approval_notional=position.approval_notional,
            approval_margin=position.approval_margin,
            fill_planned_risk=position.planned_risk,
            fill_notional=position.entry_notional,
            fill_margin=position.margin,
            approval_currency_conversion=position.approval_currency_conversion,
            entry_currency_conversion=position.entry_currency_conversion,
            exit_currency_conversion=exit_conversion,
            maximum_adverse_excursion=position.maximum_adverse_excursion,
            maximum_favourable_excursion=position.maximum_favourable_excursion,
        )
