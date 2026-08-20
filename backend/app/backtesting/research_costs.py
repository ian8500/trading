from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal

from app.backtesting.costs import CostModel, CostPreset
from app.core.decimal import ZERO
from app.opportunities import OpportunityCandidate

_BPS = Decimal("10000")


@dataclass(frozen=True, slots=True)
class _BaseCostProxy:
    spread_bps: Decimal
    slippage_bps_per_side: Decimal
    commission_bps_per_side: Decimal
    financing_bps_per_day: Decimal
    guaranteed_stop_premium_bps: Decimal


_BASE_PROXIES: dict[str, _BaseCostProxy] = {
    # REALISTIC values preserve CostModel V1 as a floor, then add transparent
    # market-specific conservative uplifts. Guaranteed stops are not simulated,
    # so their premium is zero unless a future order explicitly requests one.
    "GBPUSD": _BaseCostProxy(*map(Decimal, ("2.0", "0.50", "0.25", "0.50", "0"))),
    "EURUSD": _BaseCostProxy(*map(Decimal, ("2.1", "0.55", "0.25", "0.50", "0"))),
    "USDJPY": _BaseCostProxy(*map(Decimal, ("2.2", "0.60", "0.25", "0.55", "0"))),
    "EURGBP": _BaseCostProxy(*map(Decimal, ("2.4", "0.65", "0.25", "0.55", "0"))),
    "FTSE100": _BaseCostProxy(*map(Decimal, ("2.8", "0.75", "0.30", "0.80", "0"))),
    "SP500": _BaseCostProxy(*map(Decimal, ("2.5", "0.70", "0.30", "0.80", "0"))),
    "NASDAQ100": _BaseCostProxy(*map(Decimal, ("3.0", "0.85", "0.35", "0.90", "0"))),
    "DAX": _BaseCostProxy(*map(Decimal, ("3.2", "0.85", "0.35", "0.90", "0"))),
    "GOLD": _BaseCostProxy(*map(Decimal, ("4.0", "1.00", "0.35", "0.90", "0"))),
    "BITCOIN": _BaseCostProxy(*map(Decimal, ("12", "3.0", "0.60", "2.0", "0"))),
    "ETHEREUM": _BaseCostProxy(*map(Decimal, ("15", "4.0", "0.75", "2.5", "0"))),
}


@dataclass(frozen=True, slots=True)
class ResearchCostAssumption:
    instrument_id: str
    assumption_id: str
    model: CostModel
    provenance: str = "Versioned research proxy only; not historical or current IG quote data."

    def audit_details(self) -> dict[str, object]:
        return {
            "instrument_id": self.instrument_id,
            "assumption_id": self.assumption_id,
            "preset": self.model.preset.value,
            "spread_bps": str(self.model.spread_bps),
            "slippage_bps_per_side": str(self.model.slippage_bps_per_side),
            "commission_bps_per_side": str(self.model.commission_bps_per_side),
            "financing_bps_per_day": str(self.model.financing_bps_per_day),
            "guaranteed_stop_premium_proxy_bps": str(self.model.guaranteed_stop_premium_bps),
            "guaranteed_stop_proxy_applies_only_when_explicitly_requested": True,
            "currency_conversion_fee_bps_per_side": str(self.model.currency_conversion_bps),
            "currency_conversion_fee_estimate_basis": (
                "entry plus exit notional; rate is basis points per side"
            ),
            "historical_ig_quotes": False,
            "provenance": self.provenance,
        }


@dataclass(frozen=True, slots=True)
class ResearchCostSchedule:
    schedule_id: str = "instrument-research-costs-v1"

    def assumption_for(
        self,
        instrument_id: str,
        preset: CostPreset | str = CostPreset.REALISTIC,
    ) -> ResearchCostAssumption:
        symbol = instrument_id.upper()
        try:
            base = _BASE_PROXIES[symbol]
        except KeyError as exc:
            raise ValueError(f"no versioned research cost proxy for {symbol}") from exc
        preset = CostPreset(preset)
        multiplier = {
            CostPreset.ZERO: ZERO,
            CostPreset.OPTIMISTIC: Decimal("0.60"),
            CostPreset.REALISTIC: Decimal("1"),
            CostPreset.STRESSED: Decimal("2"),
        }[preset]
        model = CostModel(
            preset=preset,
            spread_bps=base.spread_bps * multiplier,
            slippage_bps_per_side=base.slippage_bps_per_side * multiplier,
            commission_bps_per_side=base.commission_bps_per_side * multiplier,
            financing_bps_per_day=base.financing_bps_per_day * multiplier,
            guaranteed_stop_premium_bps=base.guaranteed_stop_premium_bps * multiplier,
            currency_conversion_bps=ZERO,
        )
        return ResearchCostAssumption(
            instrument_id=symbol,
            assumption_id=f"{self.schedule_id}:{symbol}:{preset.value}",
            model=model,
        )

    def assumptions_for(
        self,
        instrument_ids: tuple[str, ...] | list[str],
        preset: CostPreset | str = CostPreset.REALISTIC,
    ) -> dict[str, ResearchCostAssumption]:
        return {
            instrument_id: self.assumption_for(instrument_id, preset)
            for instrument_id in instrument_ids
        }

    def scaled_assumption_for(
        self,
        instrument_id: str,
        multiplier: Decimal | str | int,
        *,
        base_preset: CostPreset | str = CostPreset.REALISTIC,
        scenario_id: str = "scaled",
    ) -> ResearchCostAssumption:
        """Return an exact scenario multiplier over a named base assumption."""

        factor = Decimal(str(multiplier))
        if factor < ZERO:
            raise ValueError("research cost multiplier cannot be negative")
        base = self.assumption_for(instrument_id, base_preset)
        model = base.model
        return ResearchCostAssumption(
            instrument_id=base.instrument_id,
            assumption_id=(
                f"{self.schedule_id}:{base.instrument_id}:{CostPreset(base_preset).value}:"
                f"{scenario_id}:x{factor}"
            ),
            model=CostModel(
                preset=model.preset,
                spread_bps=model.spread_bps * factor,
                slippage_bps_per_side=model.slippage_bps_per_side * factor,
                commission_bps_per_side=model.commission_bps_per_side * factor,
                financing_bps_per_day=model.financing_bps_per_day * factor,
                guaranteed_stop_premium_bps=model.guaranteed_stop_premium_bps * factor,
                currency_conversion_bps=model.currency_conversion_bps * factor,
            ),
        )


@dataclass(frozen=True, slots=True)
class EstimatedCostBreakdown:
    """Fractions of notional estimated over the candidate's full round trip.

    Spread is already a full quoted spread. Slippage, commission, and currency
    conversion are per-side model inputs and therefore appear twice here.
    """

    spread_fraction: Decimal
    round_trip_slippage_fraction: Decimal
    round_trip_commission_fraction: Decimal
    financing_fraction: Decimal
    guaranteed_stop_proxy_fraction: Decimal
    currency_conversion_fee_fraction: Decimal

    @property
    def total_fraction(self) -> Decimal:
        return (
            self.spread_fraction
            + self.round_trip_slippage_fraction
            + self.round_trip_commission_fraction
            + self.financing_fraction
            + self.guaranteed_stop_proxy_fraction
            + self.currency_conversion_fee_fraction
        )

    def audit_details(self) -> dict[str, str]:
        return {
            "spread_fraction": str(self.spread_fraction),
            "round_trip_slippage_fraction": str(self.round_trip_slippage_fraction),
            "round_trip_commission_fraction": str(self.round_trip_commission_fraction),
            "financing_fraction": str(self.financing_fraction),
            "guaranteed_stop_proxy_fraction": str(self.guaranteed_stop_proxy_fraction),
            "currency_conversion_fee_fraction": str(self.currency_conversion_fee_fraction),
            "total_fraction": str(self.total_fraction),
        }


def apply_research_cost_assumption(
    candidate: OpportunityCandidate,
    assumption: ResearchCostAssumption,
    *,
    guaranteed_stop_requested: bool = False,
) -> tuple[OpportunityCandidate, EstimatedCostBreakdown]:
    model = assumption.model
    holding_days = Decimal(str(candidate.expected_horizon.total_seconds())) / Decimal("86400")
    breakdown = EstimatedCostBreakdown(
        spread_fraction=model.spread_bps / _BPS,
        round_trip_slippage_fraction=model.slippage_bps_per_side * Decimal("2") / _BPS,
        round_trip_commission_fraction=model.commission_bps_per_side * Decimal("2") / _BPS,
        financing_fraction=model.financing_bps_per_day * holding_days / _BPS,
        guaranteed_stop_proxy_fraction=(
            model.guaranteed_stop_premium_bps / _BPS if guaranteed_stop_requested else ZERO
        ),
        currency_conversion_fee_fraction=(model.currency_conversion_bps * Decimal("2") / _BPS),
    )
    return (
        replace(
            candidate,
            estimated_spread_cost=breakdown.spread_fraction,
            estimated_slippage=breakdown.round_trip_slippage_fraction,
            estimated_financing=breakdown.financing_fraction,
            estimated_total_cost=breakdown.total_fraction,
            spread_fraction=breakdown.spread_fraction,
        ),
        breakdown,
    )


def model_cost_assumption(
    instrument_id: str,
    model: CostModel,
    *,
    assumption_id: str,
) -> ResearchCostAssumption:
    """Label a caller-supplied model as an explicit research assumption."""

    return ResearchCostAssumption(
        instrument_id=instrument_id,
        assumption_id=assumption_id,
        model=model,
        provenance=(
            "Caller-supplied research cost assumption; not historical or current IG quote data."
        ),
    )
