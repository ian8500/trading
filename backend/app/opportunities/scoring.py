from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, localcontext

from app.core.decimal import ONE, ZERO, as_decimal
from app.opportunities.models import ExpectedGrowthScore, OpportunityCandidate


@dataclass(frozen=True, slots=True)
class ExpectedGrowthScorer:
    """Score a candidate by expected log growth with visible penalties.

    Upside, downside and costs are account-return fractions (``0.01`` is 1%).
    Uncalibrated candidates use a deliberately neutral prior and receive the
    configured uncertainty penalty; confidence never increases risk limits.
    """

    uncalibrated_probability: Decimal = Decimal("0.50")
    uncalibrated_penalty: Decimal = Decimal("0.002")

    def score(self, candidate: OpportunityCandidate) -> ExpectedGrowthScore:
        probability = (
            candidate.calibrated_probability
            if candidate.calibrated_probability is not None
            else self.uncalibrated_probability
        )
        probability = min(ONE, max(ZERO, as_decimal(probability)))
        # Build the geometric edge from the gross outcome distribution, then
        # deduct the visible cost term exactly once in the total below.
        upside = max(ZERO, candidate.expected_upside)
        downside = min(Decimal("0.999999"), candidate.expected_downside)
        with localcontext() as ctx:
            ctx.prec = 28
            expected_log_growth = (
                probability * (ONE + upside).ln() + (ONE - probability) * (ONE - downside).ln()
            )

        confidence_factor = ONE if candidate.calibrated_probability is not None else Decimal("0.75")
        positive = (
            expected_log_growth
            * confidence_factor
            * candidate.regime_suitability
            * candidate.data_quality
            * candidate.strategy_health
        )
        uncertainty = candidate.uncertainty_penalty
        if candidate.calibrated_probability is None:
            uncertainty += self.uncalibrated_penalty
        total = (
            positive
            - candidate.estimated_total_cost
            - candidate.tail_risk_penalty
            - candidate.correlation_penalty
            - candidate.event_risk_penalty
            - uncertainty
        )
        return ExpectedGrowthScore(
            expected_log_growth=expected_log_growth,
            confidence_factor=confidence_factor,
            regime_factor=candidate.regime_suitability,
            data_quality_factor=candidate.data_quality,
            strategy_health_factor=candidate.strategy_health,
            cost_penalty=candidate.estimated_total_cost,
            tail_risk_penalty=candidate.tail_risk_penalty,
            correlation_penalty=candidate.correlation_penalty,
            event_risk_penalty=candidate.event_risk_penalty,
            uncertainty_penalty=uncertainty,
            total=total,
        )

    def rank(self, candidates: list[OpportunityCandidate]) -> list[OpportunityCandidate]:
        scored = [c.with_growth_score(self.score(c)) for c in candidates]
        return sorted(scored, key=lambda item: (item.score, item.instrument_id), reverse=True)
