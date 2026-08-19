from __future__ import annotations

import itertools
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.backtesting.broker import HistoricalBroker
from app.backtesting.costs import CostModel, CostPreset
from app.backtesting.data_guard import FutureDataAccessError, GuardedBarSeries, MarketView
from app.backtesting.fingerprint import SIMULATOR_BEHAVIOR_VERSION, research_fingerprint
from app.backtesting.metrics import BacktestMetrics, calculate_metrics
from app.backtesting.models import (
    AuditEvent,
    Bar,
    EquityPoint,
    ExitReason,
    FillPolicy,
    Position,
    Trade,
)
from app.challenger import ChallengeContext, DeterministicChallenger
from app.core.clock import SimulationClock
from app.core.decimal import ONE, ZERO, money
from app.instruments import Instrument
from app.opportunities import Direction, ExpectedGrowthScorer
from app.portfolio import ManagedCapitalLedger, OpenExposure, PortfolioRiskState
from app.risk import (
    ApprovedOrder,
    BreakerKind,
    RiskEngine,
    RiskLimits,
    RiskTaper,
    resolve_risk_taper,
)
from app.strategies import Strategy


@dataclass(frozen=True, slots=True)
class BacktestConfig:
    starting_equity: Decimal = Decimal("500.00")
    cost_preset: CostPreset = CostPreset.REALISTIC
    fill_policy: FillPolicy = FillPolicy.CONSERVATIVE
    execution_delay_bars: int = 1
    maximum_holding_bars: int = 48
    operational_costs: Decimal = ZERO
    seed: int = 0
    close_positions_at_end: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "starting_equity", money(self.starting_equity))
        object.__setattr__(self, "cost_preset", CostPreset(self.cost_preset))
        object.__setattr__(self, "fill_policy", FillPolicy(self.fill_policy))
        object.__setattr__(self, "operational_costs", money(self.operational_costs))
        if self.operational_costs < ZERO:
            raise ValueError("operational_costs cannot be negative")
        if self.execution_delay_bars < 1:
            raise ValueError("execution_delay_bars must be at least one (next-bar execution)")
        if self.maximum_holding_bars < 1:
            raise ValueError("maximum_holding_bars must be positive")


@dataclass(frozen=True, slots=True)
class BacktestResult:
    run_fingerprint: str
    strategy_version_id: str
    config: BacktestConfig
    trades: tuple[Trade, ...]
    equity_curve: tuple[EquityPoint, ...]
    audit_trail: tuple[AuditEvent, ...]
    metrics: BacktestMetrics
    rejected_candidates: int
    broker_orders_submitted: int


@dataclass(frozen=True, slots=True)
class _PendingOrder:
    due_index: int
    order: ApprovedOrder


class HistoricalBacktestEngine:
    """Chronological simulator: completed bar -> signal -> next-bar execution."""

    def __init__(
        self,
        instrument: Instrument,
        strategy: Strategy,
        *,
        risk_limits: RiskLimits | None = None,
        challenger: DeterministicChallenger | None = None,
        scorer: ExpectedGrowthScorer | None = None,
        cost_model: CostModel | None = None,
        risk_taper: RiskTaper | bool | None = False,
    ) -> None:
        self.instrument = instrument
        self.strategy = strategy
        self.risk_limits = risk_limits or RiskLimits()
        self.challenger = challenger or DeterministicChallenger()
        self.scorer = scorer or ExpectedGrowthScorer()
        self._cost_model_override = cost_model
        self.risk_taper = resolve_risk_taper(risk_taper)

    def run(self, bars: Sequence[Bar], config: BacktestConfig | None = None) -> BacktestResult:
        config = config or BacktestConfig()
        bars = tuple(sorted(bars, key=lambda item: item.timestamp))
        self._validate_bars(bars)
        clock = SimulationClock(bars[0].timestamp)
        guarded = GuardedBarSeries(bars, clock)
        view = MarketView(self.instrument, guarded)
        ledger = ManagedCapitalLedger(config.starting_equity)
        risk_engine = RiskEngine(self.risk_limits, clock=clock, risk_taper=self.risk_taper)
        cost_model = self._cost_model_override or CostModel.from_preset(config.cost_preset)
        broker = HistoricalBroker(self.instrument, cost_model)
        pending: list[_PendingOrder] = []
        positions: list[Position] = []
        trades: list[Trade] = []
        curve: list[EquityPoint] = []
        audit: list[AuditEvent] = []
        rejected = 0
        peak_equity = ledger.equity
        sequence = 0

        def record(timestamp: datetime, event_type: str, details: dict[str, Any]) -> None:
            nonlocal sequence
            sequence += 1
            audit.append(AuditEvent(sequence, timestamp, event_type, details))

        for index, bar in enumerate(bars):
            clock.advance_to(bar.timestamp)
            for kind in risk_engine.refresh_period_boundaries(bar.timestamp):
                record(
                    bar.timestamp,
                    "CIRCUIT_BREAKER_RESET",
                    {"kind": kind.value, "reason": "UTC accounting period ended"},
                )
            record(bar.timestamp, "MARKET_BAR_COMPLETED", {"close": str(bar.close), "index": index})

            due = [item for item in pending if item.due_index <= index]
            pending = [item for item in pending if item.due_index > index]
            for pending_order in due:
                position = broker.execute_order(pending_order.order, bar)
                positions.append(position)
                record(
                    bar.timestamp,
                    "ORDER_FILLED",
                    {
                        "position_id": position.position_id,
                        "requested_entry": str(position.requested_entry),
                        "actual_entry": str(position.actual_entry),
                        "size": str(position.quantity),
                        "stop": str(position.stop_price),
                        "target": None
                        if position.target_price is None
                        else str(position.target_price),
                        "risk_decision_id": position.risk_decision_id,
                    },
                )

            remaining: list[Position] = []
            for position in positions:
                updated = self._mark_position(position, bar)
                exit_request = self._exit_for_bar(updated, bar, config.fill_policy)
                if exit_request is None and updated.bars_held >= config.maximum_holding_bars:
                    exit_request = (bar.close, ExitReason.TIME)
                if exit_request is None and not risk_engine.breakers.healthy:
                    exit_request = (bar.close, ExitReason.CIRCUIT_BREAKER)
                if exit_request is None:
                    remaining.append(updated)
                    continue
                requested_exit, reason = exit_request
                trade = broker.close_position(updated, requested_exit, bar, reason, ledger)
                trades.append(trade)
                record(
                    bar.timestamp,
                    "POSITION_CLOSED",
                    {
                        "trade_id": trade.trade_id,
                        "reason": reason.value,
                        "gross_pnl": str(trade.gross_pnl),
                        "costs": str(trade.total_cost),
                        "net_pnl": str(trade.net_pnl),
                        "equity_before": str(trade.managed_equity_before),
                        "equity_after": str(trade.managed_equity_after),
                    },
                )
            positions = remaining

            has_same_strategy_exposure = bool(positions or pending)
            if ledger.equity > ZERO and not has_same_strategy_exposure:
                try:
                    candidate = self.strategy.evaluate(view)
                except FutureDataAccessError:
                    risk_engine.breakers.trip(
                        BreakerKind.STRATEGY_EXCEPTION,
                        "strategy attempted future-data access",
                        bar.timestamp,
                    )
                    record(
                        bar.timestamp, "LOOKAHEAD_BLOCKED", {"strategy": self.strategy.version_id}
                    )
                    raise
                except Exception as exc:
                    risk_engine.breakers.trip(
                        BreakerKind.STRATEGY_EXCEPTION,
                        f"strategy exception: {type(exc).__name__}",
                        bar.timestamp,
                    )
                    record(
                        bar.timestamp,
                        "STRATEGY_EXCEPTION",
                        {"exception_type": type(exc).__name__},
                    )
                    candidate = None
                if candidate is not None:
                    candidate = candidate.with_growth_score(self.scorer.score(candidate))
                    record(
                        bar.timestamp,
                        "CANDIDATE_CREATED",
                        {
                            "instrument_id": candidate.instrument_id,
                            "strategy_version_id": candidate.strategy_version_id,
                            "direction": candidate.direction.value,
                            "raw_score": str(candidate.raw_signal_score),
                            "expected_growth_score": str(candidate.score),
                            "regime": candidate.regime,
                            "estimated_total_cost": str(candidate.estimated_total_cost),
                            "explanation": candidate.structured_explanation,
                        },
                    )
                    recent_move = ZERO if index == 0 else bar.close / bars[index - 1].close - ONE
                    challenge = self.challenger.challenge(
                        candidate,
                        ChallengeContext(now=bar.timestamp, recent_move=recent_move),
                    )
                    record(
                        bar.timestamp,
                        "CANDIDATE_CHALLENGED",
                        {
                            "approved": challenge.approved,
                            "original_score": str(challenge.original_score),
                            "revised_score": str(challenge.revised_score),
                            "penalties": {
                                key: str(value) for key, value in challenge.penalties.items()
                            },
                            "rejection_reasons": list(challenge.rejection_reasons),
                        },
                    )
                    if challenge.approved:
                        portfolio = self._portfolio_state(
                            positions,
                            trades,
                            ledger,
                            peak_equity,
                            now=bar.timestamp,
                        )
                        decision = risk_engine.evaluate(
                            candidate,
                            self.instrument,
                            ledger,
                            portfolio,
                            now=bar.timestamp,
                        )
                        record(
                            bar.timestamp,
                            "RISK_DECISION",
                            {
                                "approved": decision.approved,
                                "decision_id": decision.decision_id,
                                "equity_basis": str(decision.equity_basis),
                                "risk_fraction": str(decision.risk_fraction),
                                "risk_taper_cap": (
                                    None
                                    if self.risk_taper is None
                                    else str(self.risk_taper.fraction_for(decision.equity_basis))
                                ),
                                "position_size": str(decision.position_size),
                                "planned_monetary_risk": str(decision.planned_monetary_risk),
                                "reasons": list(decision.reasons),
                            },
                        )
                        if decision.approved:
                            stop = candidate.proposed_stop_distance or (
                                candidate.signal_price * candidate.expected_downside
                            )
                            target = candidate.proposed_target_distance
                            if target is None:
                                target = stop * candidate.reward_risk_ratio
                            pending.append(
                                _PendingOrder(
                                    index + config.execution_delay_bars,
                                    ApprovedOrder(candidate, decision, stop, target),
                                )
                            )
                            record(
                                bar.timestamp,
                                "ORDER_SCHEDULED",
                                {"execution_bar_index": index + config.execution_delay_bars},
                            )
                        else:
                            rejected += 1
                    else:
                        rejected += 1

            unrealised = sum(
                (self._unrealised(position, bar.close) for position in positions), ZERO
            )
            marked_equity = money(ledger.equity + unrealised)
            peak_equity = max(peak_equity, marked_equity)
            drawdown = ZERO if peak_equity <= ZERO else (peak_equity - marked_equity) / peak_equity
            exposure = money(
                sum(
                    (
                        position.quantity
                        * bar.close
                        * self.instrument.contract_size
                        * self.instrument.currency_conversion
                        for position in positions
                    ),
                    ZERO,
                )
            )
            curve.append(EquityPoint(bar.timestamp, marked_equity, peak_equity, drawdown, exposure))
            if marked_equity <= ZERO:
                risk_engine.breakers.trip(
                    BreakerKind.TOTAL_DRAWDOWN, "managed equity exhausted", bar.timestamp
                )

        if positions and config.close_positions_at_end:
            final_bar = bars[-1]
            for position in positions:
                trade = broker.close_position(
                    position, final_bar.close, final_bar, ExitReason.END_OF_DATA, ledger
                )
                trades.append(trade)
                record(
                    final_bar.timestamp,
                    "POSITION_CLOSED",
                    {
                        "trade_id": trade.trade_id,
                        "reason": ExitReason.END_OF_DATA.value,
                        "net_pnl": str(trade.net_pnl),
                        "equity_after": str(trade.managed_equity_after),
                    },
                )
            if curve:
                peak_equity = max(peak_equity, ledger.equity)
                curve[-1] = EquityPoint(
                    final_bar.timestamp,
                    ledger.equity,
                    peak_equity,
                    ZERO if peak_equity <= ZERO else (peak_equity - ledger.equity) / peak_equity,
                    ZERO,
                )
        for expired in pending:
            record(
                bars[-1].timestamp,
                "ORDER_EXPIRED_END_OF_DATA",
                {"decision_id": expired.order.decision.decision_id},
            )

        metrics = calculate_metrics(
            config.starting_equity,
            trades,
            curve,
            operational_costs=config.operational_costs,
        )
        return BacktestResult(
            run_fingerprint=self._fingerprint(bars, config, cost_model),
            strategy_version_id=self.strategy.version_id,
            config=config,
            trades=tuple(trades),
            equity_curve=tuple(curve),
            audit_trail=tuple(audit),
            metrics=metrics,
            rejected_candidates=rejected,
            broker_orders_submitted=broker.submitted_order_count,
        )

    def _validate_bars(self, bars: Sequence[Bar]) -> None:
        if len(bars) < 2:
            raise ValueError("at least two completed bars are required")
        if any(a.timestamp >= b.timestamp for a, b in itertools.pairwise(bars)):
            raise ValueError("bar timestamps must be unique and increasing")
        for bar in bars:
            if bar.instrument_id and bar.instrument_id != self.instrument.id:
                raise ValueError("bar instrument does not match engine instrument")

    def _mark_position(self, position: Position, bar: Bar) -> Position:
        if position.direction is Direction.LONG:
            adverse = max(ZERO, position.actual_entry - bar.low)
            favourable = max(ZERO, bar.high - position.actual_entry)
        else:
            adverse = max(ZERO, bar.high - position.actual_entry)
            favourable = max(ZERO, position.actual_entry - bar.low)
        return replace(
            position,
            bars_held=position.bars_held + 1,
            maximum_adverse_excursion=max(position.maximum_adverse_excursion, adverse),
            maximum_favourable_excursion=max(position.maximum_favourable_excursion, favourable),
        )

    @staticmethod
    def _exit_for_bar(
        position: Position,
        bar: Bar,
        policy: FillPolicy,
    ) -> tuple[Decimal, ExitReason] | None:
        if position.direction is Direction.LONG:
            if bar.open <= position.stop_price:
                return bar.open, ExitReason.STOP
            if position.target_price is not None and bar.open >= position.target_price:
                return bar.open, ExitReason.TARGET
            stop_touched = bar.low <= position.stop_price
            target_touched = position.target_price is not None and bar.high >= position.target_price
        else:
            if bar.open >= position.stop_price:
                return bar.open, ExitReason.STOP
            if position.target_price is not None and bar.open <= position.target_price:
                return bar.open, ExitReason.TARGET
            stop_touched = bar.high >= position.stop_price
            target_touched = position.target_price is not None and bar.low <= position.target_price
        if stop_touched and target_touched:
            if policy is FillPolicy.TARGET_FIRST:
                return position.target_price, ExitReason.TARGET  # type: ignore[return-value]
            # CONSERVATIVE, STOP_FIRST and unavailable lower timeframe all fail safe.
            return position.stop_price, ExitReason.STOP
        if stop_touched:
            return position.stop_price, ExitReason.STOP
        if target_touched:
            return position.target_price, ExitReason.TARGET  # type: ignore[return-value]
        return None

    def _unrealised(self, position: Position, price: Decimal) -> Decimal:
        return money(
            (price - position.requested_entry)
            * position.direction.multiplier
            * position.quantity
            * self.instrument.point_value
            * self.instrument.contract_size
            * self.instrument.currency_conversion
        )

    def _portfolio_state(
        self,
        positions: Sequence[Position],
        trades: Sequence[Trade],
        ledger: ManagedCapitalLedger,
        peak_equity: Decimal,
        *,
        now: datetime,
    ) -> PortfolioRiskState:
        exposures = tuple(
            OpenExposure(
                position.instrument_id,
                position.direction,
                position.planned_risk,
                position.requested_entry
                * position.quantity
                * self.instrument.contract_size
                * self.instrument.currency_conversion,
                position.margin,
                self.instrument.correlation_cluster,
                position.strategy_version_id,
                self.instrument.exposure_tags,
            )
            for position in positions
        )
        if trades:
            daily_loss = abs(
                sum(
                    (
                        trade.net_pnl
                        for trade in trades
                        if trade.exit_timestamp.date() == now.date() and trade.net_pnl < ZERO
                    ),
                    ZERO,
                )
            )
            week = now.isocalendar()[:2]
            weekly_loss = abs(
                sum(
                    (
                        trade.net_pnl
                        for trade in trades
                        if trade.exit_timestamp.isocalendar()[:2] == week and trade.net_pnl < ZERO
                    ),
                    ZERO,
                )
            )
        else:
            daily_loss = weekly_loss = ZERO
        return PortfolioRiskState(exposures, daily_loss, weekly_loss, peak_equity)

    def _fingerprint(
        self,
        bars: Sequence[Bar],
        config: BacktestConfig,
        effective_cost_model: CostModel,
    ) -> str:
        payload = {
            "engine": "HistoricalBacktestEngine",
            "simulator_behavior_version": SIMULATOR_BEHAVIOR_VERSION,
            "backtest_config": config,
            "effective_cost_model": effective_cost_model,
            "instrument": self.instrument,
            "strategy_version_id": self.strategy.version_id,
            "strategy": self.strategy,
            "risk_limits": self.risk_limits,
            "risk_taper": self.risk_taper,
            "challenger": self.challenger,
            "growth_scorer": self.scorer,
            "completed_bars": tuple(bars),
        }
        return research_fingerprint(payload)


BacktestEngine = HistoricalBacktestEngine
