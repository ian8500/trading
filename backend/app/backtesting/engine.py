from __future__ import annotations

import itertools
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.backtesting.broker import HistoricalBroker
from app.backtesting.conversion import (
    ConversionBoundary,
    ConversionQuote,
    ConversionTimingPolicy,
    ConversionUnavailableError,
    QuoteToGbpConversionPolicy,
)
from app.backtesting.costs import CostModel, CostPreset
from app.backtesting.data_guard import FutureDataAccessError, GuardedBarSeries, MarketView
from app.backtesting.fill_revalidation import FillRiskRevalidationPolicy
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
from app.backtesting.research_costs import (
    EstimatedCostBreakdown,
    ResearchCostAssumption,
    apply_research_cost_assumption,
    model_cost_assumption,
)
from app.backtesting.sessions import MarketSessionPolicy, SessionDecision
from app.challenger import ChallengeContext, DeterministicChallenger
from app.core.clock import SimulationClock
from app.core.decimal import ONE, ZERO, money
from app.instruments import Instrument
from app.opportunities import Direction, ExpectedGrowthScorer, OpportunityCandidate
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
    bar_interval: str = "1d"

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
        if self.bar_interval not in {"15m", "30m", "1h", "1d"}:
            raise ValueError("bar_interval must be one of 15m, 30m, 1h or 1d")


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
    approval_conversion: ConversionQuote


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
        cost_assumption: ResearchCostAssumption | None = None,
        conversion_policy: QuoteToGbpConversionPolicy | None = None,
        conversion_timing_policy: ConversionTimingPolicy | None = None,
        fill_revalidation_policy: FillRiskRevalidationPolicy | None = None,
        session_policy: MarketSessionPolicy | None = None,
        risk_taper: RiskTaper | bool | None = False,
    ) -> None:
        self.instrument = instrument
        self.strategy = strategy
        self.risk_limits = risk_limits or RiskLimits()
        self.challenger = challenger or DeterministicChallenger()
        self.scorer = scorer or ExpectedGrowthScorer()
        if cost_model is not None and cost_assumption is not None:
            raise ValueError("provide cost_model or cost_assumption, not both")
        if cost_assumption is not None and cost_assumption.instrument_id != instrument.id:
            raise ValueError("cost assumption instrument does not match engine instrument")
        self._cost_model_override = cost_model
        self._cost_assumption_override = cost_assumption
        self.conversion_policy = conversion_policy or QuoteToGbpConversionPolicy.causal()
        self.conversion_timing_policy = conversion_timing_policy or ConversionTimingPolicy()
        self.fill_revalidation_policy = fill_revalidation_policy or FillRiskRevalidationPolicy()
        self.session_policy = session_policy or MarketSessionPolicy()
        self.risk_taper = resolve_risk_taper(risk_taper)

    def run(
        self,
        bars: Sequence[Bar],
        config: BacktestConfig | None = None,
        *,
        reference_bars_by_instrument: Mapping[str, Sequence[Bar]] | None = None,
    ) -> BacktestResult:
        config = config or BacktestConfig()
        bars = tuple(sorted(bars, key=lambda item: item.timestamp))
        self._validate_bars(bars)
        reference_bars = self._validate_reference_bars(reference_bars_by_instrument or {})
        conversion_bars = self._merge_conversion_bars(
            reference_bars,
            {self.instrument.id: bars},
        )
        resolver = self.conversion_policy.build(
            conversion_bars,
            interval=config.bar_interval,
        )
        clock = SimulationClock(bars[0].timestamp)
        guarded = GuardedBarSeries(bars, clock)
        view = MarketView(self.instrument, guarded)
        ledger = ManagedCapitalLedger(config.starting_equity)
        risk_engine = RiskEngine(self.risk_limits, clock=clock, risk_taper=self.risk_taper)
        cost_model = (
            self._cost_assumption_override.model
            if self._cost_assumption_override is not None
            else self._cost_model_override or CostModel.from_preset(config.cost_preset)
        )
        cost_assumption = self._cost_assumption_override or model_cost_assumption(
            self.instrument.id,
            cost_model,
            assumption_id=f"engine-cost-model:{self.instrument.id}:{config.cost_preset.value}",
        )
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

        record(
            bars[0].timestamp,
            "RESEARCH_ASSUMPTIONS",
            {
                "simulator_behavior_version": SIMULATOR_BEHAVIOR_VERSION,
                "instrument_id": self.instrument.id,
                "instrument_economics": self._instrument_economics(self.instrument),
                "cost_assumption": cost_assumption.audit_details(),
                "conversion_policy": self.conversion_policy.audit_details(),
                "conversion_timing_policy": self.conversion_timing_policy.audit_details(
                    interval=config.bar_interval
                ),
                "fill_revalidation_policy": self.fill_revalidation_policy.audit_details(),
                "session_policy": self.session_policy.audit_details(),
                "reference_instruments": sorted(reference_bars),
            },
        )

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
                entry_at = self.conversion_timing_policy.execution_as_of(
                    bar,
                    interval=config.bar_interval,
                )
                if entry_at < pending_order.order.candidate.timestamp:
                    rejected += 1
                    record(
                        bar.timestamp,
                        "ORDER_REJECTED_FILL_TIMING",
                        {
                            "decision_id": pending_order.order.decision.decision_id,
                            "original_signal_at": (
                                pending_order.order.candidate.timestamp.isoformat()
                            ),
                            "modeled_entry_at": entry_at.isoformat(),
                            "fill_processed_at": bar.timestamp.isoformat(),
                            "conversion_timing_policy": (
                                self.conversion_timing_policy.audit_details(
                                    interval=config.bar_interval
                                )
                            ),
                            "fill_revalidation_policy": (
                                self.fill_revalidation_policy.audit_details()
                            ),
                            "reason": "modeled fill would precede its approval signal",
                        },
                    )
                    continue
                session = self.session_policy.at_fill(
                    self.instrument,
                    pending_order.order.candidate.timestamp,
                    bar,
                    interval=config.bar_interval,
                )
                if not session.eligible:
                    rejected += 1
                    record(
                        bar.timestamp,
                        "ORDER_REJECTED_SESSION",
                        {
                            "decision_id": pending_order.order.decision.decision_id,
                            "session": session.audit_details(),
                        },
                    )
                    continue
                try:
                    entry_conversion = self.conversion_timing_policy.resolve_execution(
                        resolver,
                        self.instrument.quote_currency,
                        bar,
                        interval=config.bar_interval,
                    )
                except ConversionUnavailableError as exc:
                    rejected += 1
                    record(
                        bar.timestamp,
                        "ORDER_REJECTED_CONVERSION",
                        {
                            "decision_id": pending_order.order.decision.decision_id,
                            "execution_as_of": entry_at.isoformat(),
                            "timing_policy": self.conversion_timing_policy.audit_details(
                                interval=config.bar_interval
                            ),
                            "reason": str(exc),
                        },
                    )
                    continue
                revalidation = self.fill_revalidation_policy.evaluate(
                    pending_order.order,
                    self.instrument,
                    starting_capital=ledger.starting_capital,
                    entry_price=bar.open,
                    entry_conversion=entry_conversion.rate_to_gbp,
                    entry_at=entry_at,
                    risk_limits=self.risk_limits,
                    risk_taper=self.risk_taper,
                )
                if not revalidation.approved:
                    rejected += 1
                    record(
                        bar.timestamp,
                        "ORDER_REJECTED_FILL_RISK",
                        {
                            "modeled_entry_at": entry_at.isoformat(),
                            "fill_processed_at": bar.timestamp.isoformat(),
                            "approval_conversion": (
                                pending_order.approval_conversion.audit_details()
                            ),
                            "entry_conversion": entry_conversion.audit_details(),
                            "fill_revalidation_policy": (
                                self.fill_revalidation_policy.audit_details()
                            ),
                            **revalidation.audit_details(),
                        },
                    )
                    continue
                fill_order = revalidation.fill_order
                assert fill_order is not None
                position = broker.execute_order(
                    fill_order,
                    bar,
                    entry_at=entry_at,
                    approval_signal_at=pending_order.order.candidate.timestamp,
                    approval_decision=pending_order.order.decision,
                    approval_currency_conversion=(pending_order.approval_conversion.rate_to_gbp),
                    entry_currency_conversion=entry_conversion.rate_to_gbp,
                )
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
                        "fill_risk_decision_id": position.fill_risk_decision_id,
                        "fill_revalidation_policy": (self.fill_revalidation_policy.audit_details()),
                        **revalidation.audit_details(),
                        "modeled_entry_at": position.entry_timestamp.isoformat(),
                        "fill_processed_at": bar.timestamp.isoformat(),
                        "conversion_timing": self.conversion_timing_policy.audit_details(
                            interval=config.bar_interval
                        ),
                        "approval_conversion": (pending_order.approval_conversion.audit_details()),
                        "entry_conversion": entry_conversion.audit_details(),
                        "entry_costs": {
                            "spread": str(position.entry_spread_cost),
                            "slippage": str(position.entry_slippage_cost),
                            "commission": str(position.entry_commission),
                            "guaranteed_stop_premium": str(position.entry_guaranteed_stop_premium),
                            "currency_conversion": str(position.entry_currency_conversion_cost),
                        },
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
                exit_conversion = self.conversion_timing_policy.resolve_execution(
                    resolver,
                    self.instrument.quote_currency,
                    bar,
                    interval=config.bar_interval,
                )
                trade = broker.close_position(
                    updated,
                    requested_exit,
                    bar,
                    reason,
                    ledger,
                    exit_currency_conversion=exit_conversion.rate_to_gbp,
                )
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
                        "approval_currency_conversion": str(trade.approval_currency_conversion),
                        "entry_currency_conversion": str(trade.entry_currency_conversion),
                        "exit_conversion": exit_conversion.audit_details(),
                        "conversion_timing": self.conversion_timing_policy.audit_details(
                            interval=config.bar_interval
                        ),
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
                    session = self.session_policy.at_signal(
                        self.instrument,
                        bar,
                        interval=config.bar_interval,
                    )
                    if not session.eligible:
                        rejected += 1
                        record(
                            bar.timestamp,
                            "CANDIDATE_REJECTED_SESSION",
                            {
                                "instrument_id": candidate.instrument_id,
                                "session": session.audit_details(),
                            },
                        )
                        candidate = None
                if candidate is not None:
                    candidate, cost_breakdown = apply_research_cost_assumption(
                        candidate,
                        cost_assumption,
                    )
                    candidate = candidate.with_growth_score(self.scorer.score(candidate))
                    record(
                        bar.timestamp,
                        "CANDIDATE_CREATED",
                        self._candidate_details(
                            candidate,
                            cost_assumption,
                            cost_breakdown,
                            session,
                        ),
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
                            "supporting_factors": list(challenge.supporting_factors),
                            "rejection_reasons": list(challenge.rejection_reasons),
                        },
                    )
                    if challenge.approved:
                        approval_conversion: ConversionQuote | None
                        try:
                            approval_conversion = resolver.resolve(
                                self.instrument.quote_currency,
                                as_of=bar.timestamp,
                                boundary=ConversionBoundary.AT_OR_BEFORE,
                            )
                        except ConversionUnavailableError as exc:
                            rejected += 1
                            record(
                                bar.timestamp,
                                "CANDIDATE_REJECTED_CONVERSION",
                                {
                                    "instrument_id": candidate.instrument_id,
                                    "boundary": ConversionBoundary.AT_OR_BEFORE.value,
                                    "reason": str(exc),
                                },
                            )
                            approval_conversion = None
                        if approval_conversion is not None:
                            effective_instrument = replace(
                                self.instrument,
                                currency_conversion=approval_conversion.rate_to_gbp,
                            )
                            portfolio = self._portfolio_state(
                                positions,
                                trades,
                                ledger,
                                peak_equity,
                                pending=pending,
                                now=bar.timestamp,
                            )
                            decision = risk_engine.evaluate(
                                candidate,
                                effective_instrument,
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
                                    "realised_ledger_equity": str(ledger.equity),
                                    "risk_fraction": str(decision.risk_fraction),
                                    "risk_taper_cap": (
                                        None
                                        if self.risk_taper is None
                                        else str(
                                            self.risk_taper.fraction_for(decision.equity_basis)
                                        )
                                    ),
                                    "position_size": str(decision.position_size),
                                    "planned_monetary_risk": str(decision.planned_monetary_risk),
                                    "notional": str(decision.notional),
                                    "margin_required": str(decision.margin_required),
                                    "conversion": approval_conversion.audit_details(),
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
                                        approval_conversion,
                                    )
                                )
                                record(
                                    bar.timestamp,
                                    "ORDER_SCHEDULED",
                                    {"execution_bar_index": (index + config.execution_delay_bars)},
                                )
                            else:
                                rejected += 1
                    else:
                        rejected += 1

            mark_instrument = self.instrument
            if positions:
                mark_conversion = resolver.resolve(
                    self.instrument.quote_currency,
                    as_of=bar.timestamp,
                    boundary=ConversionBoundary.AT_OR_BEFORE,
                )
                mark_instrument = replace(
                    self.instrument,
                    currency_conversion=mark_conversion.rate_to_gbp,
                )
            unrealised = sum(
                (self._unrealised(position, bar.close, mark_instrument) for position in positions),
                ZERO,
            )
            marked_equity = money(ledger.equity + unrealised)
            peak_equity = max(peak_equity, marked_equity)
            drawdown = ZERO if peak_equity <= ZERO else (peak_equity - marked_equity) / peak_equity
            exposure = money(
                sum(
                    (
                        position.quantity
                        * bar.close
                        * mark_instrument.contract_size
                        * mark_instrument.currency_conversion
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
            exit_conversion = self.conversion_timing_policy.resolve_execution(
                resolver,
                self.instrument.quote_currency,
                final_bar,
                interval=config.bar_interval,
            )
            for position in positions:
                trade = broker.close_position(
                    position,
                    final_bar.close,
                    final_bar,
                    ExitReason.END_OF_DATA,
                    ledger,
                    exit_currency_conversion=exit_conversion.rate_to_gbp,
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
                        "exit_conversion": exit_conversion.audit_details(),
                        "conversion_timing": self.conversion_timing_policy.audit_details(
                            interval=config.bar_interval
                        ),
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
            run_fingerprint=self._fingerprint(
                bars,
                reference_bars,
                config,
                cost_assumption,
            ),
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

    @staticmethod
    def _validate_reference_bars(
        bars_by_instrument: Mapping[str, Sequence[Bar]],
    ) -> dict[str, tuple[Bar, ...]]:
        references: dict[str, tuple[Bar, ...]] = {}
        for instrument_id, source in bars_by_instrument.items():
            bars = tuple(sorted(source, key=lambda bar: bar.timestamp))
            if not bars:
                raise ValueError(f"{instrument_id} reference bars cannot be empty")
            if any(left.timestamp >= right.timestamp for left, right in itertools.pairwise(bars)):
                raise ValueError(f"{instrument_id} reference timestamps must be unique")
            if any(bar.instrument_id and bar.instrument_id != instrument_id for bar in bars):
                raise ValueError(f"{instrument_id} contains a mismatched reference bar")
            references[instrument_id] = bars
        return references

    @staticmethod
    def _merge_conversion_bars(
        references: Mapping[str, Sequence[Bar]],
        trading: Mapping[str, Sequence[Bar]],
    ) -> dict[str, tuple[Bar, ...]]:
        merged: dict[str, tuple[Bar, ...]] = {}
        for instrument_id in sorted(set(references) | set(trading)):
            by_timestamp: dict[datetime, Bar] = {}
            for source in (references.get(instrument_id, ()), trading.get(instrument_id, ())):
                for bar in source:
                    previous = by_timestamp.get(bar.timestamp)
                    if previous is not None and previous != bar:
                        raise ValueError(
                            f"{instrument_id} has conflicting trading/reference bars at "
                            f"{bar.timestamp.isoformat()}"
                        )
                    by_timestamp[bar.timestamp] = bar
            merged[instrument_id] = tuple(
                by_timestamp[timestamp] for timestamp in sorted(by_timestamp)
            )
        return merged

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

    def _unrealised(
        self,
        position: Position,
        price: Decimal,
        instrument: Instrument | None = None,
    ) -> Decimal:
        effective = instrument or self.instrument
        gross = money(
            (price - position.requested_entry)
            * position.direction.multiplier
            * position.quantity
            * effective.point_value
            * effective.contract_size
            * effective.currency_conversion
        )
        incurred_entry_costs = money(
            position.entry_spread_cost
            + position.entry_slippage_cost
            + position.entry_commission
            + position.entry_guaranteed_stop_premium
            + position.entry_currency_conversion_cost
        )
        return money(gross - incurred_entry_costs)

    def _portfolio_state(
        self,
        positions: Sequence[Position],
        trades: Sequence[Trade],
        ledger: ManagedCapitalLedger,
        peak_equity: Decimal,
        *,
        pending: Sequence[_PendingOrder] = (),
        now: datetime,
    ) -> PortfolioRiskState:
        exposures = [
            OpenExposure(
                position.instrument_id,
                position.direction,
                position.planned_risk,
                position.entry_notional,
                position.margin,
                self.instrument.correlation_cluster,
                position.strategy_version_id,
                self.instrument.exposure_tags,
            )
            for position in positions
        ]
        exposures.extend(
            OpenExposure(
                item.order.candidate.instrument_id,
                item.order.candidate.direction,
                item.order.decision.planned_monetary_risk,
                item.order.decision.notional,
                item.order.decision.margin_required,
                item.order.candidate.correlation_cluster or self.instrument.correlation_cluster,
                item.order.candidate.strategy_version_id,
                self.instrument.exposure_tags,
            )
            for item in pending
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
        return PortfolioRiskState(tuple(exposures), daily_loss, weekly_loss, peak_equity)

    def _fingerprint(
        self,
        bars: Sequence[Bar],
        reference_bars: Mapping[str, Sequence[Bar]],
        config: BacktestConfig,
        cost_assumption: ResearchCostAssumption,
    ) -> str:
        payload = {
            "engine": "HistoricalBacktestEngine",
            "simulator_behavior_version": SIMULATOR_BEHAVIOR_VERSION,
            "backtest_config": config,
            "effective_cost_assumption": cost_assumption,
            "conversion_policy": self.conversion_policy,
            "conversion_timing_policy": self.conversion_timing_policy,
            "fill_revalidation_policy": self.fill_revalidation_policy,
            "session_policy": self.session_policy,
            "instrument": self.instrument,
            "strategy_version_id": self.strategy.version_id,
            "strategy": self.strategy,
            "risk_limits": self.risk_limits,
            "risk_taper": self.risk_taper,
            "challenger": self.challenger,
            "growth_scorer": self.scorer,
            "completed_bars": tuple(bars),
            "reference_completed_bars_by_instrument": {
                key: tuple(reference_bars[key]) for key in sorted(reference_bars)
            },
        }
        return research_fingerprint(payload)

    @staticmethod
    def _instrument_economics(instrument: Instrument) -> dict[str, object]:
        return {
            "economics_version": instrument.economics_version,
            "provenance": instrument.economics_provenance,
            "point_value": str(instrument.point_value),
            "contract_size": str(instrument.contract_size),
            "minimum_size": str(instrument.min_deal_size),
            "size_step": str(instrument.size_step),
            "margin_factor": str(instrument.margin_factor),
            "quote_currency": instrument.quote_currency,
        }

    @staticmethod
    def _candidate_details(
        candidate: OpportunityCandidate,
        assumption: ResearchCostAssumption,
        costs: EstimatedCostBreakdown,
        session: SessionDecision,
    ) -> dict[str, object]:
        score = candidate.expected_growth_score
        return {
            "instrument_id": candidate.instrument_id,
            "strategy_version_id": candidate.strategy_version_id,
            "direction": candidate.direction.value,
            "signal_price": str(candidate.signal_price),
            "expected_horizon_seconds": int(candidate.expected_horizon.total_seconds()),
            "raw_score": str(candidate.raw_signal_score),
            "calibrated_probability": (
                None
                if candidate.calibrated_probability is None
                else str(candidate.calibrated_probability)
            ),
            "expected_upside": str(candidate.expected_upside),
            "expected_downside": str(candidate.expected_downside),
            "reward_risk_ratio": str(candidate.reward_risk_ratio),
            "estimated_spread_cost": str(candidate.estimated_spread_cost),
            "estimated_slippage": str(candidate.estimated_slippage),
            "estimated_financing": str(candidate.estimated_financing),
            "estimated_total_cost": str(candidate.estimated_total_cost),
            "effective_cost_assumption": assumption.audit_details(),
            "estimated_cost_breakdown": costs.audit_details(),
            "volatility": str(candidate.volatility),
            "liquidity_score": str(candidate.liquidity_score),
            "regime": candidate.regime,
            "regime_suitability": str(candidate.regime_suitability),
            "historical_support": candidate.historical_support,
            "data_quality": str(candidate.data_quality),
            "strategy_health": str(candidate.strategy_health),
            "correlation_penalty": str(candidate.correlation_penalty),
            "event_risk_penalty": str(candidate.event_risk_penalty),
            "uncertainty_penalty": str(candidate.uncertainty_penalty),
            "tail_risk_penalty": str(candidate.tail_risk_penalty),
            "expected_growth_score": str(candidate.score),
            "score_components": (
                None
                if score is None
                else {
                    field_name: str(getattr(score, field_name))
                    for field_name in score.__dataclass_fields__
                }
            ),
            "session": session.audit_details(),
            "explanation": candidate.structured_explanation,
        }


BacktestEngine = HistoricalBacktestEngine
