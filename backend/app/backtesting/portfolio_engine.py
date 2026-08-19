from __future__ import annotations

import itertools
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.backtesting.broker import HistoricalBroker
from app.backtesting.costs import CostModel
from app.backtesting.data_guard import FutureDataAccessError, GuardedBarSeries, MarketView
from app.backtesting.engine import BacktestConfig
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
from app.core.decimal import ZERO, money
from app.instruments import Instrument
from app.opportunities import ExpectedGrowthScorer, OpportunityCandidate
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
class PortfolioBacktestResult:
    run_fingerprint: str
    config: BacktestConfig
    strategy_versions: dict[str, str]
    trades: tuple[Trade, ...]
    equity_curve: tuple[EquityPoint, ...]
    audit_trail: tuple[AuditEvent, ...]
    metrics: BacktestMetrics
    rejected_candidates: int
    broker_orders_submitted: int
    orders_by_instrument: dict[str, int]


@dataclass(frozen=True, slots=True)
class _PortfolioPendingOrder:
    instrument_id: str
    due_local_index: int
    order: ApprovedOrder


class PortfolioBacktestEngine:
    """Multi-market chronological simulator with one shared managed ledger.

    Bars from all instruments are merged by completion timestamp.  Candidates
    produced at the same timestamp are scored and ranked together; challenge
    and risk gates then run in rank order.  Approved-but-not-yet-filled orders
    reserve portfolio and correlation risk so a second candidate cannot bypass
    limits while both wait for their next instrument bar.
    """

    def __init__(
        self,
        instruments: Mapping[str, Instrument],
        strategies: Mapping[str, Strategy],
        *,
        risk_limits: RiskLimits | None = None,
        challenger: DeterministicChallenger | None = None,
        scorer: ExpectedGrowthScorer | None = None,
        cost_models: Mapping[str, CostModel] | None = None,
        risk_taper: RiskTaper | bool | None = False,
    ) -> None:
        if not instruments:
            raise ValueError("at least one instrument is required")
        missing = set(instruments) - set(strategies)
        if missing:
            raise ValueError(f"strategies missing for instruments: {sorted(missing)}")
        self.instruments = dict(instruments)
        self.strategies = dict(strategies)
        self.risk_limits = risk_limits or RiskLimits()
        self.challenger = challenger or DeterministicChallenger()
        self.scorer = scorer or ExpectedGrowthScorer()
        self.cost_models = dict(cost_models or {})
        self.risk_taper = resolve_risk_taper(risk_taper)

    def run(
        self,
        bars_by_instrument: Mapping[str, Sequence[Bar]],
        config: BacktestConfig | None = None,
    ) -> PortfolioBacktestResult:
        config = config or BacktestConfig()
        datasets = self._validate_data(bars_by_instrument)
        event_times = sorted({bar.timestamp for bars in datasets.values() for bar in bars})
        clock = SimulationClock(event_times[0])
        views = {
            instrument_id: MarketView(
                self.instruments[instrument_id],
                GuardedBarSeries(bars, clock),
            )
            for instrument_id, bars in datasets.items()
        }
        local_indices = {
            instrument_id: {bar.timestamp: index for index, bar in enumerate(bars)}
            for instrument_id, bars in datasets.items()
        }
        bars_at_time: dict[datetime, list[tuple[str, Bar]]] = {}
        for instrument_id, bars in datasets.items():
            for bar in bars:
                bars_at_time.setdefault(bar.timestamp, []).append((instrument_id, bar))
        ledger = ManagedCapitalLedger(config.starting_equity)
        risk_engine = RiskEngine(
            self.risk_limits,
            clock=clock,
            risk_taper=self.risk_taper,
        )
        brokers = {
            instrument_id: HistoricalBroker(
                instrument,
                self.cost_models.get(instrument_id) or CostModel.from_preset(config.cost_preset),
            )
            for instrument_id, instrument in self.instruments.items()
            if instrument_id in datasets
        }
        pending: list[_PortfolioPendingOrder] = []
        positions: dict[str, Position] = {}
        trades: list[Trade] = []
        curve: list[EquityPoint] = []
        audit: list[AuditEvent] = []
        last_prices: dict[str, Decimal] = {}
        rejected = 0
        peak_equity = ledger.equity
        sequence = 0

        def record(timestamp: datetime, event_type: str, details: dict[str, Any]) -> None:
            nonlocal sequence
            sequence += 1
            audit.append(AuditEvent(sequence, timestamp, event_type, details))

        for timestamp in event_times:
            clock.advance_to(timestamp)
            for kind in risk_engine.refresh_period_boundaries(timestamp):
                record(
                    timestamp,
                    "CIRCUIT_BREAKER_RESET",
                    {"kind": kind.value, "reason": "UTC accounting period ended"},
                )
            updated = sorted(bars_at_time[timestamp], key=lambda item: item[0])
            {instrument_id for instrument_id, _ in updated}
            for instrument_id, bar in updated:
                last_prices[instrument_id] = bar.close
                record(
                    timestamp,
                    "MARKET_BAR_COMPLETED",
                    {
                        "instrument_id": instrument_id,
                        "local_index": local_indices[instrument_id][timestamp],
                        "close": str(bar.close),
                    },
                )

            # Each order waits for the next bar of its own market, never merely
            # the next event belonging to another instrument.
            remaining_pending: list[_PortfolioPendingOrder] = []
            for item in pending:
                local_index = local_indices[item.instrument_id].get(timestamp)
                if local_index is None or local_index < item.due_local_index:
                    remaining_pending.append(item)
                    continue
                bar = datasets[item.instrument_id][local_index]
                position = brokers[item.instrument_id].execute_order(item.order, bar)
                positions[position.position_id] = position
                record(
                    timestamp,
                    "ORDER_FILLED",
                    {
                        "instrument_id": item.instrument_id,
                        "position_id": position.position_id,
                        "size": str(position.quantity),
                        "requested_entry": str(position.requested_entry),
                        "actual_entry": str(position.actual_entry),
                        "risk_decision_id": position.risk_decision_id,
                    },
                )
            pending = remaining_pending

            for instrument_id, bar in updated:
                local_index = local_indices[instrument_id][timestamp]
                is_last_bar = local_index == len(datasets[instrument_id]) - 1
                for position_id, position in list(positions.items()):
                    if position.instrument_id != instrument_id:
                        continue
                    updated_position = self._mark_position(position, bar)
                    exit_request = self._exit_for_bar(updated_position, bar, config.fill_policy)
                    if (
                        exit_request is None
                        and updated_position.bars_held >= config.maximum_holding_bars
                    ):
                        exit_request = (bar.close, ExitReason.TIME)
                    if exit_request is None and not risk_engine.breakers.healthy:
                        exit_request = (bar.close, ExitReason.CIRCUIT_BREAKER)
                    if exit_request is None and is_last_bar and config.close_positions_at_end:
                        exit_request = (bar.close, ExitReason.END_OF_DATA)
                    if exit_request is None:
                        positions[position_id] = updated_position
                        continue
                    requested_exit, reason = exit_request
                    trade = brokers[instrument_id].close_position(
                        updated_position,
                        requested_exit,
                        bar,
                        reason,
                        ledger,
                    )
                    del positions[position_id]
                    trades.append(trade)
                    record(
                        timestamp,
                        "POSITION_CLOSED",
                        {
                            "instrument_id": instrument_id,
                            "trade_id": trade.trade_id,
                            "reason": reason.value,
                            "net_pnl": str(trade.net_pnl),
                            "equity_before": str(trade.managed_equity_before),
                            "equity_after": str(trade.managed_equity_after),
                        },
                    )

            candidates: list[OpportunityCandidate] = []
            for instrument_id, _bar in updated:
                local_index = local_indices[instrument_id][timestamp]
                has_future_execution_bar = local_index + config.execution_delay_bars < len(
                    datasets[instrument_id]
                )
                exposed = any(
                    position.instrument_id == instrument_id for position in positions.values()
                ) or any(item.instrument_id == instrument_id for item in pending)
                if not has_future_execution_bar or exposed or ledger.equity <= ZERO:
                    continue
                try:
                    candidate = self.strategies[instrument_id].evaluate(views[instrument_id])
                except FutureDataAccessError:
                    risk_engine.breakers.trip(
                        BreakerKind.STRATEGY_EXCEPTION,
                        f"{instrument_id} strategy attempted future-data access",
                        timestamp,
                    )
                    record(timestamp, "LOOKAHEAD_BLOCKED", {"instrument_id": instrument_id})
                    raise
                except Exception as exc:
                    risk_engine.breakers.trip(
                        BreakerKind.STRATEGY_EXCEPTION,
                        f"strategy exception: {type(exc).__name__}",
                        timestamp,
                    )
                    record(
                        timestamp,
                        "STRATEGY_EXCEPTION",
                        {"instrument_id": instrument_id, "exception_type": type(exc).__name__},
                    )
                    continue
                if candidate is None:
                    continue
                if candidate.instrument_id != instrument_id:
                    raise ValueError("strategy candidate instrument does not match its market view")
                candidate = candidate.with_growth_score(self.scorer.score(candidate))
                candidates.append(candidate)
                record(
                    timestamp,
                    "CANDIDATE_CREATED",
                    {
                        "instrument_id": instrument_id,
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
                        "score_components": self._score_components(candidate),
                        "explanation": candidate.structured_explanation,
                    },
                )

            ranked = sorted(
                candidates, key=lambda candidate: (-candidate.score, candidate.instrument_id)
            )
            if ranked:
                record(
                    timestamp,
                    "CANDIDATES_RANKED",
                    {
                        "ranking": [
                            {
                                "rank": rank,
                                "instrument_id": candidate.instrument_id,
                                "expected_growth_score": str(candidate.score),
                            }
                            for rank, candidate in enumerate(ranked, 1)
                        ]
                    },
                )
            for candidate in ranked:
                context = ChallengeContext(now=timestamp)
                challenge = self.challenger.challenge(candidate, context)
                record(
                    timestamp,
                    "CANDIDATE_CHALLENGED",
                    {
                        "instrument_id": candidate.instrument_id,
                        "approved": challenge.approved,
                        "original_score": str(challenge.original_score),
                        "revised_score": str(challenge.revised_score),
                        "supporting_factors": list(challenge.supporting_factors),
                        "penalties": {
                            key: str(value) for key, value in challenge.penalties.items()
                        },
                        "rejection_reasons": list(challenge.rejection_reasons),
                    },
                )
                if not challenge.approved:
                    rejected += 1
                    continue
                portfolio = self._portfolio_state(
                    positions.values(),
                    pending,
                    trades,
                    ledger,
                    peak_equity,
                    now=timestamp,
                )
                decision = risk_engine.evaluate(
                    candidate,
                    self.instruments[candidate.instrument_id],
                    ledger,
                    portfolio,
                    now=timestamp,
                )
                record(
                    timestamp,
                    "RISK_DECISION",
                    {
                        "instrument_id": candidate.instrument_id,
                        "rank": ranked.index(candidate) + 1,
                        "approved": decision.approved,
                        "decision_id": decision.decision_id,
                        "equity_basis": str(decision.equity_basis),
                        "risk_fraction": str(decision.risk_fraction),
                        "risk_taper_cap": (
                            None
                            if self.risk_taper is None
                            else str(self.risk_taper.fraction_for(decision.equity_basis))
                        ),
                        "planned_monetary_risk": str(decision.planned_monetary_risk),
                        "reasons": list(decision.reasons),
                    },
                )
                if not decision.approved:
                    rejected += 1
                    continue
                stop = candidate.proposed_stop_distance or (
                    candidate.signal_price * candidate.expected_downside
                )
                target = candidate.proposed_target_distance or (stop * candidate.reward_risk_ratio)
                local_index = local_indices[candidate.instrument_id][timestamp]
                pending.append(
                    _PortfolioPendingOrder(
                        candidate.instrument_id,
                        local_index + config.execution_delay_bars,
                        ApprovedOrder(candidate, decision, stop, target),
                    )
                )
                record(
                    timestamp,
                    "ORDER_SCHEDULED",
                    {
                        "instrument_id": candidate.instrument_id,
                        "execution_local_index": local_index + config.execution_delay_bars,
                    },
                )

            unrealised = sum(
                (
                    self._unrealised(
                        position,
                        last_prices.get(position.instrument_id, position.requested_entry),
                        self.instruments[position.instrument_id],
                    )
                    for position in positions.values()
                ),
                ZERO,
            )
            equity = money(ledger.equity + unrealised)
            peak_equity = max(peak_equity, equity)
            drawdown = ZERO if peak_equity <= ZERO else (peak_equity - equity) / peak_equity
            exposure = money(
                sum(
                    (
                        position.quantity
                        * last_prices.get(position.instrument_id, position.requested_entry)
                        * self.instruments[position.instrument_id].contract_size
                        * self.instruments[position.instrument_id].currency_conversion
                        for position in positions.values()
                    ),
                    ZERO,
                )
            )
            curve.append(EquityPoint(timestamp, equity, peak_equity, drawdown, exposure))

        # Any pending order lacked a legitimate next bar and is never sent.
        for item in pending:
            record(
                event_times[-1],
                "ORDER_EXPIRED_END_OF_DATA",
                {
                    "instrument_id": item.instrument_id,
                    "decision_id": item.order.decision.decision_id,
                },
            )
        metrics = calculate_metrics(
            config.starting_equity,
            trades,
            curve,
            operational_costs=config.operational_costs,
        )
        orders_by_instrument = {
            instrument_id: broker.submitted_order_count for instrument_id, broker in brokers.items()
        }
        return PortfolioBacktestResult(
            run_fingerprint=self._fingerprint(
                datasets,
                config,
                {instrument_id: broker.cost_model for instrument_id, broker in brokers.items()},
            ),
            config=config,
            strategy_versions={
                instrument_id: self.strategies[instrument_id].version_id
                for instrument_id in datasets
            },
            trades=tuple(trades),
            equity_curve=tuple(curve),
            audit_trail=tuple(audit),
            metrics=metrics,
            rejected_candidates=rejected,
            broker_orders_submitted=sum(orders_by_instrument.values()),
            orders_by_instrument=orders_by_instrument,
        )

    def _validate_data(
        self, bars_by_instrument: Mapping[str, Sequence[Bar]]
    ) -> dict[str, tuple[Bar, ...]]:
        unknown = set(bars_by_instrument) - set(self.instruments)
        if unknown:
            raise ValueError(f"data supplied for unknown instruments: {sorted(unknown)}")
        datasets: dict[str, tuple[Bar, ...]] = {}
        for instrument_id, source in bars_by_instrument.items():
            bars = tuple(sorted(source, key=lambda bar: bar.timestamp))
            if len(bars) < 2:
                raise ValueError(f"{instrument_id} requires at least two bars")
            if any(left.timestamp >= right.timestamp for left, right in itertools.pairwise(bars)):
                raise ValueError(f"{instrument_id} bar timestamps must be unique")
            if any(bar.instrument_id and bar.instrument_id != instrument_id for bar in bars):
                raise ValueError(f"{instrument_id} contains a mismatched bar instrument")
            datasets[instrument_id] = bars
        if not datasets:
            raise ValueError("bars_by_instrument cannot be empty")
        return datasets

    @staticmethod
    def _mark_position(position: Position, bar: Bar) -> Position:
        if position.direction.value == "LONG":
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
        from app.backtesting.engine import HistoricalBacktestEngine

        return HistoricalBacktestEngine._exit_for_bar(position, bar, policy)

    @staticmethod
    def _unrealised(position: Position, price: Decimal, instrument: Instrument) -> Decimal:
        return money(
            (price - position.requested_entry)
            * position.direction.multiplier
            * position.quantity
            * instrument.point_value
            * instrument.contract_size
            * instrument.currency_conversion
        )

    def _portfolio_state(
        self,
        positions: Iterable[Position],
        pending: Sequence[_PortfolioPendingOrder],
        trades: Sequence[Trade],
        ledger: ManagedCapitalLedger,
        peak_equity: Decimal,
        *,
        now: datetime,
    ) -> PortfolioRiskState:
        exposures: list[OpenExposure] = []
        for position in positions:
            instrument = self.instruments[position.instrument_id]
            exposures.append(
                OpenExposure(
                    position.instrument_id,
                    position.direction,
                    position.planned_risk,
                    position.requested_entry
                    * position.quantity
                    * instrument.contract_size
                    * instrument.currency_conversion,
                    position.margin,
                    instrument.correlation_cluster,
                    position.strategy_version_id,
                    instrument.exposure_tags,
                )
            )
        for item in pending:
            instrument = self.instruments[item.instrument_id]
            exposures.append(
                OpenExposure(
                    item.instrument_id,
                    item.order.candidate.direction,
                    item.order.decision.planned_monetary_risk,
                    item.order.decision.notional,
                    item.order.decision.margin_required,
                    item.order.candidate.correlation_cluster or instrument.correlation_cluster,
                    item.order.candidate.strategy_version_id,
                    instrument.exposure_tags,
                )
            )
        if trades:
            daily = abs(
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
            weekly = abs(
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
            daily = weekly = ZERO
        return PortfolioRiskState(tuple(exposures), daily, weekly, peak_equity)

    def _fingerprint(
        self,
        datasets: Mapping[str, Sequence[Bar]],
        config: BacktestConfig,
        effective_cost_models: Mapping[str, CostModel],
    ) -> str:
        participating_ids = tuple(sorted(datasets))
        payload = {
            "engine": "PortfolioBacktestEngine",
            "simulator_behavior_version": SIMULATOR_BEHAVIOR_VERSION,
            "backtest_config": config,
            "effective_cost_models": {key: effective_cost_models[key] for key in participating_ids},
            "instruments": {key: self.instruments[key] for key in participating_ids},
            "strategy_version_ids": {
                key: self.strategies[key].version_id for key in participating_ids
            },
            "strategies": {key: self.strategies[key] for key in participating_ids},
            "risk_limits": self.risk_limits,
            "risk_taper": self.risk_taper,
            "challenger": self.challenger,
            "growth_scorer": self.scorer,
            "completed_bars_by_instrument": {
                key: tuple(datasets[key]) for key in participating_ids
            },
        }
        return research_fingerprint(payload)

    @staticmethod
    def _score_components(candidate: OpportunityCandidate) -> dict[str, str] | None:
        score = candidate.expected_growth_score
        if score is None:
            return None
        return {
            field_name: str(getattr(score, field_name)) for field_name in score.__dataclass_fields__
        }
