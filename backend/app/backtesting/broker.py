from __future__ import annotations

import hashlib
from decimal import Decimal

from app.backtesting.costs import CostModel, calculate_exit_costs, monetary_price_distance
from app.backtesting.models import Bar, ExitReason, Position, Trade
from app.core.decimal import money
from app.instruments import Instrument
from app.portfolio import ManagedCapitalLedger
from app.risk import ApprovedOrder


class BrokerBoundaryError(RuntimeError):
    pass


class HistoricalBroker:
    """Deterministic historical broker that only accepts risk capability objects."""

    def __init__(self, instrument: Instrument, cost_model: CostModel | None = None) -> None:
        self.instrument = instrument
        self.cost_model = cost_model or CostModel.from_preset("REALISTIC")
        self.submitted_order_count = 0
        self.fills: list[Position] = []

    def execute_order(self, order: ApprovedOrder, bar: Bar) -> Position:
        if not isinstance(order, ApprovedOrder) or not order.decision.approved:
            raise BrokerBoundaryError("orders must carry an approved RiskEngine decision")
        if order.candidate.instrument_id != self.instrument.id:
            raise BrokerBoundaryError("instrument mismatch")
        if bar.timestamp <= order.candidate.timestamp:
            raise BrokerBoundaryError("historical entry must occur after the signal bar")
        self.submitted_order_count += 1
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
                bar.timestamp.isoformat(),
                self.instrument.id,
            )
        )
        position = Position(
            position_id=hashlib.sha256(key.encode()).hexdigest()[:24],
            instrument_id=self.instrument.id,
            strategy_version_id=order.candidate.strategy_version_id,
            direction=order.candidate.direction,
            quantity=order.decision.position_size,
            entry_timestamp=bar.timestamp,
            requested_entry=requested,
            actual_entry=actual,
            stop_price=stop,
            target_price=target,
            entry_spread_cost=monetary_price_distance(
                half_spread, order.decision.position_size, self.instrument
            ),
            entry_slippage_cost=monetary_price_distance(
                slippage, order.decision.position_size, self.instrument
            ),
            planned_risk=order.decision.planned_monetary_risk,
            margin=order.decision.margin_required,
            regime=order.candidate.regime,
            candidate_score=order.candidate.score,
            risk_decision_id=order.decision.decision_id,
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
    ) -> Trade:
        half_spread = self.cost_model.half_spread_price(bar, requested_exit)
        slippage = self.cost_model.slippage_price(requested_exit)
        adverse = half_spread + slippage
        actual_exit = requested_exit - position.direction.multiplier * adverse
        holding_seconds = max(0, int((bar.timestamp - position.entry_timestamp).total_seconds()))
        gross = money(
            (requested_exit - position.requested_entry)
            * position.direction.multiplier
            * position.quantity
            * self.instrument.point_value
            * self.instrument.contract_size
            * self.instrument.currency_conversion
        )
        costs = calculate_exit_costs(
            self.cost_model,
            position,
            bar,
            requested_exit,
            self.instrument,
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
            maximum_adverse_excursion=position.maximum_adverse_excursion,
            maximum_favourable_excursion=position.maximum_favourable_excursion,
        )
