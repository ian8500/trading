from __future__ import annotations

import hashlib
from datetime import datetime
from decimal import Decimal

from app.core.clock import Clock, SystemClock
from app.core.decimal import ZERO, money
from app.instruments import Instrument
from app.opportunities import OpportunityCandidate
from app.portfolio import ManagedCapitalLedger, PortfolioRiskState
from app.risk.circuit_breakers import BreakerKind, CircuitBreakerRegistry
from app.risk.models import ApprovedOrder, RiskDecision, RiskLimits, StrategyHealth
from app.risk.position_sizing import PositionSizer, PositionSizingRequest
from app.risk.taper import RiskTaper, resolve_risk_taper


class RiskEngine:
    """Authoritative, deterministic and fail-closed execution gate."""

    def __init__(
        self,
        limits: RiskLimits | None = None,
        *,
        clock: Clock | None = None,
        breakers: CircuitBreakerRegistry | None = None,
        position_sizer: PositionSizer | None = None,
        risk_taper: RiskTaper | bool | None = False,
    ) -> None:
        self.limits = limits or RiskLimits()
        self.clock = clock or SystemClock()
        self.breakers = breakers or CircuitBreakerRegistry()
        self.position_sizer = position_sizer or PositionSizer()
        self.risk_taper = resolve_risk_taper(risk_taper)

    def refresh_period_boundaries(self, timestamp: datetime) -> tuple[BreakerKind, ...]:
        """Expire UTC daily/ISO-week loss gates without touching hard breakers."""

        return self.breakers.reset_expired_periods(timestamp)

    def evaluate(
        self,
        candidate: OpportunityCandidate,
        instrument: Instrument,
        ledger: ManagedCapitalLedger,
        portfolio: PortfolioRiskState | None = None,
        *,
        strategy_health: StrategyHealth = StrategyHealth.NORMAL,
        now: datetime | None = None,
        managed_equity: Decimal | None = None,
    ) -> RiskDecision:
        portfolio = portfolio or PortfolioRiskState()
        timestamp = now or self.clock.now()
        self.refresh_period_boundaries(timestamp)
        equity = ledger.equity if managed_equity is None else money(managed_equity)
        reasons: list[str] = list(self.breakers.rejection_reasons())

        age = timestamp - candidate.timestamp
        if age.total_seconds() < 0:
            self.breakers.trip(
                BreakerKind.CLOCK_ANOMALY, "candidate timestamp is in the future", timestamp
            )
            reasons.append("candidate timestamp is in the future")
        elif age > self.limits.max_data_age:
            self.breakers.trip(BreakerKind.STALE_PRICING, "candidate data is stale", timestamp)
            reasons.append("stale data")
        if candidate.signal_price <= ZERO:
            self.breakers.trip(BreakerKind.IMPOSSIBLE_PRICE, "non-positive signal price", timestamp)
            reasons.append("impossible price")
        if not instrument.tradeable or not instrument.market_open or not candidate.market_open:
            reasons.append("market is not tradeable and open")
        if strategy_health in (StrategyHealth.SUSPENDED, StrategyHealth.OBSERVATION_ONLY):
            reasons.append(f"strategy health is {strategy_health.value}")
        if candidate.reward_risk_ratio < self.limits.min_reward_risk:
            reasons.append("reward-to-risk ratio below minimum")
        if candidate.spread_fraction > self.limits.max_spread_fraction:
            self.breakers.trip(
                BreakerKind.ABNORMAL_SPREAD, "spread exceeds configured maximum", timestamp
            )
            reasons.append("abnormal spread")
        if candidate.data_quality < self.limits.min_data_quality:
            reasons.append("data quality below minimum")
        if len(portfolio.positions) >= self.limits.max_concurrent_positions:
            reasons.append("maximum concurrent positions reached")
        if equity <= ZERO:
            reasons.append("managed equity is exhausted")

        requested_fraction = candidate.requested_risk_fraction or self.limits.risk_per_trade
        if requested_fraction > self.limits.risk_per_trade:
            reasons.append("requested trade risk exceeds profile limit")
        effective_risk_fraction = min(requested_fraction, self.limits.risk_per_trade)
        if strategy_health is StrategyHealth.REDUCED_RISK:
            effective_risk_fraction = min(
                effective_risk_fraction,
                self.limits.risk_per_trade / Decimal("2"),
            )
        if self.risk_taper is not None:
            effective_risk_fraction = min(
                effective_risk_fraction,
                self.risk_taper.fraction_for(equity),
            )

        if portfolio.daily_loss > equity * self.limits.max_daily_loss:
            self.breakers.trip(BreakerKind.DAILY_LOSS, "daily loss limit reached", timestamp)
            reasons.append("daily loss circuit breaker")
        if portfolio.weekly_loss > equity * self.limits.max_weekly_loss:
            self.breakers.trip(BreakerKind.WEEKLY_LOSS, "weekly loss limit reached", timestamp)
            reasons.append("weekly loss circuit breaker")
        if portfolio.peak_equity and portfolio.peak_equity > ZERO:
            drawdown = (portfolio.peak_equity - equity) / portfolio.peak_equity
            if drawdown > self.limits.max_rolling_drawdown:
                self.breakers.trip(
                    BreakerKind.ROLLING_DRAWDOWN,
                    "rolling drawdown limit reached",
                    timestamp,
                )
                reasons.append("rolling drawdown circuit breaker")
        total_drawdown = max(
            ZERO,
            (ledger.starting_capital - equity) / ledger.starting_capital,
        )
        if total_drawdown > self.limits.max_total_drawdown:
            self.breakers.trip(
                BreakerKind.TOTAL_DRAWDOWN,
                "total drawdown limit reached",
                timestamp,
            )
            reasons.append("total drawdown circuit breaker")

        stop_distance = candidate.proposed_stop_distance or (
            candidate.signal_price * candidate.expected_downside
        )
        estimated_cost_per_unit = (
            candidate.signal_price
            * candidate.estimated_total_cost
            * instrument.point_value
            * instrument.contract_size
            * instrument.currency_conversion
        )
        sizing = self.position_sizer.calculate(
            PositionSizingRequest(
                equity=equity,
                risk_fraction=effective_risk_fraction,
                entry_price=candidate.signal_price,
                stop_distance=stop_distance,
                instrument=instrument,
                expected_cost_per_unit=estimated_cost_per_unit,
                available_margin=max(ZERO, equity - portfolio.margin_used),
            )
        )
        if not sizing.accepted:
            reasons.append(sizing.reason or "position sizing rejected")
        if portfolio.open_risk + sizing.actual_risk > equity * self.limits.max_open_risk:
            reasons.append("maximum open portfolio risk exceeded")
        if sizing.notional > equity * self.limits.max_market_exposure:
            reasons.append("maximum individual market exposure exceeded")
        if (
            equity > ZERO
            and (portfolio.gross_notional + sizing.notional) / equity
            > self.limits.max_effective_leverage
        ):
            reasons.append("maximum effective leverage exceeded")
        if portfolio.margin_used + sizing.margin_required > equity * self.limits.max_margin_usage:
            reasons.append("maximum margin usage exceeded")
        cluster = candidate.correlation_cluster or instrument.correlation_cluster
        correlated = portfolio.correlation_risk(cluster, candidate.direction)
        if correlated + sizing.actual_risk > equity * self.limits.max_correlated_risk:
            reasons.append("maximum correlated exposure exceeded")

        # A breaker may have been tripped by checks above; fail closed immediately.
        for reason in self.breakers.rejection_reasons():
            if reason not in reasons:
                reasons.append(reason)
        approved = not reasons and sizing.accepted
        decision_id = self._decision_id(
            candidate,
            instrument,
            equity,
            effective_risk_fraction,
            sizing.size,
            sizing.actual_risk,
            sizing.notional,
            sizing.margin_required,
            tuple(reasons),
        )
        return RiskDecision(
            decision_id=decision_id,
            approved=approved,
            reasons=tuple(reasons),
            equity_basis=equity,
            risk_fraction=effective_risk_fraction,
            permitted_risk=sizing.permitted_risk,
            position_size=sizing.size if approved else ZERO,
            planned_monetary_risk=sizing.actual_risk if approved else ZERO,
            notional=sizing.notional if approved else ZERO,
            margin_required=sizing.margin_required if approved else ZERO,
        )

    def approve_order(
        self,
        candidate: OpportunityCandidate,
        instrument: Instrument,
        ledger: ManagedCapitalLedger,
        portfolio: PortfolioRiskState | None = None,
        *,
        strategy_health: StrategyHealth = StrategyHealth.NORMAL,
        now: datetime | None = None,
        managed_equity: Decimal | None = None,
    ) -> ApprovedOrder | None:
        decision = self.evaluate(
            candidate,
            instrument,
            ledger,
            portfolio,
            strategy_health=strategy_health,
            now=now,
            managed_equity=managed_equity,
        )
        if not decision.approved:
            return None
        stop = (
            candidate.proposed_stop_distance or candidate.signal_price * candidate.expected_downside
        )
        target = candidate.proposed_target_distance
        if target is None and candidate.reward_risk_ratio > ZERO:
            target = stop * candidate.reward_risk_ratio
        return ApprovedOrder(candidate, decision, stop, target)

    @staticmethod
    def _decision_id(
        candidate: OpportunityCandidate,
        instrument: Instrument,
        equity: Decimal,
        risk_fraction: Decimal,
        position_size: Decimal,
        planned_risk: Decimal,
        notional: Decimal,
        margin: Decimal,
        reasons: tuple[str, ...],
    ) -> str:
        payload = "|".join(
            (
                candidate.timestamp.isoformat(),
                candidate.instrument_id,
                candidate.strategy_version_id,
                str(equity),
                str(risk_fraction),
                instrument.economics_version,
                str(instrument.point_value),
                str(instrument.contract_size),
                str(instrument.min_deal_size),
                str(instrument.size_step),
                str(instrument.currency_conversion),
                str(position_size),
                str(planned_risk),
                str(notional),
                str(margin),
                *reasons,
            )
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
