from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.backtesting import BacktestConfig, Bar, FillPolicy
from app.backtesting.costs import CostPreset
from app.backtesting.metrics import BacktestMetrics, calculate_metrics
from app.backtesting.models import EquityPoint
from app.backtesting.monte_carlo import TradeSequenceMonteCarlo
from app.backtesting.portfolio_engine import PortfolioBacktestEngine, PortfolioBacktestResult
from app.backtesting.stress import STANDARD_STRESS_SCENARIOS, apply_stress
from app.database.models import (
    AuditEventRecord,
    BacktestRecord,
    DataManifestRecord,
    HistoricalBarRecord,
    InstrumentRecord,
    ManagedCapitalLedgerRecord,
    OpportunityRecord,
    TradeRecord,
)
from app.instruments import AssetClass, Instrument
from app.instruments.catalog import CORE_UNIVERSE
from app.risk import RiskProfile, limits_for_profile
from app.strategies import RegimeEnsembleStrategy, Strategy, TrendBreakoutStrategy
from app.strategies.trend_breakout import TrendBreakoutConfig

DISPLAY_NAMES = {definition.symbol: definition.name for definition in CORE_UNIVERSE.values()}
SYMBOLS_BY_NAME = {name: symbol for symbol, name in DISPLAY_NAMES.items()}
SUPPORTED_STRATEGIES = ("Quant Baseline", "Quant Aggressive", "Regime Ensemble")

_CONVERSION_TO_GBP = {
    "GBP": Decimal("1"),
    "USD": Decimal("0.78"),
    "EUR": Decimal("0.86"),
    "JPY": Decimal("0.0053"),
}
_CLUSTERS = {
    "GBPUSD": "GBP_FX",
    "EURUSD": "EUR_FX",
    "USDJPY": "USD_FX",
    "EURGBP": "EUR_GBP_FX",
    "FTSE100": "UK_EQUITY",
    "SP500": "US_EQUITY",
    "NASDAQ100": "US_EQUITY",
    "DAX": "EU_EQUITY",
    "GOLD": "PRECIOUS_METALS",
    "BITCOIN": "CRYPTO",
    "ETHEREUM": "CRYPTO",
}
_EXPOSURE_TAGS = {
    "GBPUSD": frozenset(("GBP_LONG", "USD_SHORT")),
    "EURUSD": frozenset(("EUR_LONG", "USD_SHORT")),
    "USDJPY": frozenset(("USD_LONG", "JPY_SHORT")),
    "EURGBP": frozenset(("EUR_LONG", "GBP_SHORT")),
    "FTSE100": frozenset(("UK_EQUITY_BETA",)),
    "SP500": frozenset(("US_EQUITY_BETA",)),
    "NASDAQ100": frozenset(("US_EQUITY_BETA", "US_TECH_BETA")),
    "DAX": frozenset(("EU_EQUITY_BETA",)),
    "GOLD": frozenset(("PRECIOUS_METALS",)),
    "BITCOIN": frozenset(("CRYPTO_BETA",)),
    "ETHEREUM": frozenset(("CRYPTO_BETA",)),
}


@dataclass(frozen=True, slots=True)
class BacktestRunRequest:
    name: str
    strategy: str
    symbols: tuple[str, ...]
    start: datetime
    end: datetime
    interval: str = "1d"
    starting_equity: Decimal = Decimal("500")
    risk_profile: RiskProfile = RiskProfile.STANDARD
    cost_preset: CostPreset = CostPreset.REALISTIC
    maximum_holding_bars: int = 2
    seed: int = 8500
    operational_costs: Decimal = Decimal("0")
    risk_taper: bool = False

    def __post_init__(self) -> None:
        if self.strategy not in SUPPORTED_STRATEGIES:
            raise ValueError(f"unsupported strategy: {self.strategy}")
        if not self.symbols:
            raise ValueError("at least one instrument is required")
        unknown = set(self.symbols) - set(CORE_UNIVERSE)
        if unknown:
            raise ValueError(f"unknown instruments: {sorted(unknown)}")
        start = _as_utc(self.start)
        end = _as_utc(self.end)
        if start >= end:
            raise ValueError("backtest start must precede end")
        if self.interval not in {"1d", "1h"}:
            raise ValueError("only genuine imported 1d and 1h bars are supported")
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)
        object.__setattr__(self, "starting_equity", Decimal(str(self.starting_equity)))
        object.__setattr__(self, "risk_profile", RiskProfile(self.risk_profile))
        object.__setattr__(self, "cost_preset", CostPreset(self.cost_preset))
        object.__setattr__(self, "operational_costs", Decimal(str(self.operational_costs)))


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def parse_boundary(value: str, *, end: bool = False) -> datetime:
    """Parse an API date/time. A date-only end is inclusive of that date."""

    try:
        if "T" not in value:
            parsed_date = date.fromisoformat(value)
            result = datetime.combine(parsed_date, time.min, tzinfo=UTC)
            return result + timedelta(days=1) if end else result
        return _as_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError as exc:
        raise ValueError(f"invalid ISO date/time: {value}") from exc


def canonical_symbol(value: str) -> str:
    compact = value.replace("/", "").replace(" ", "").upper()
    aliases = {
        "FTSE": "FTSE100",
        "S&P500": "SP500",
        "S&P500INDEX": "SP500",
        "NASDAQ": "NASDAQ100",
        "GOLDFUTURES": "GOLD",
    }
    if value in SYMBOLS_BY_NAME:
        return SYMBOLS_BY_NAME[value]
    return aliases.get(compact, compact)


def _instrument(symbol: str) -> Instrument:
    definition = CORE_UNIVERSE[symbol]
    return Instrument(
        id=definition.symbol,
        name=definition.name,
        asset_class=AssetClass(definition.asset_class),
        quote_currency=definition.currency,
        point_value=definition.point_value,
        min_deal_size=definition.minimum_size,
        margin_factor=definition.margin_factor,
        currency_conversion=_CONVERSION_TO_GBP.get(definition.currency, Decimal("1")),
        correlation_cluster=_CLUSTERS.get(symbol),
        exposure_tags=_EXPOSURE_TAGS.get(symbol, frozenset()),
    )


def _strategy(name: str, symbol: str) -> Strategy:
    if name == "Quant Baseline":
        return TrendBreakoutStrategy(version_id=f"quant-baseline-v1:{symbol}")
    if name == "Quant Aggressive":
        config = TrendBreakoutConfig(
            fast_period=5,
            slow_period=20,
            momentum_period=5,
            breakout_period=12,
            atr_period=14,
            atr_stop_multiple=Decimal("1.25"),
            reward_risk_ratio=Decimal("1.75"),
            maximum_extension_atr=Decimal("4"),
            minimum_raw_score=Decimal("0.08"),
            expected_horizon=timedelta(hours=12),
        )
        return TrendBreakoutStrategy(version_id=f"quant-aggressive-v1:{symbol}", config=config)
    return RegimeEnsembleStrategy(version_id=f"regime-ensemble-v1:{symbol}")


def _load_bars(
    session: Session, request: BacktestRunRequest
) -> tuple[dict[str, tuple[Bar, ...]], list[str], dict[str, str]]:
    output: dict[str, tuple[Bar, ...]] = {}
    checksums: dict[str, str] = {}
    for symbol in request.symbols:
        instrument_row = session.scalar(
            select(InstrumentRecord).where(InstrumentRecord.symbol == symbol)
        )
        if instrument_row is None:
            raise ValueError(f"{symbol} has not been imported")
        rows = tuple(
            session.scalars(
                select(HistoricalBarRecord)
                .where(
                    HistoricalBarRecord.instrument_id == instrument_row.id,
                    HistoricalBarRecord.provider == "Yahoo Finance",
                    HistoricalBarRecord.interval == request.interval,
                    HistoricalBarRecord.timestamp >= request.start.replace(tzinfo=None),
                    HistoricalBarRecord.timestamp < request.end.replace(tzinfo=None),
                    HistoricalBarRecord.complete.is_(True),
                )
                .order_by(HistoricalBarRecord.timestamp)
            )
        )
        if len(rows) < 2:
            raise ValueError(
                f"{symbol} has insufficient {request.interval} data in the requested period"
            )
        output[symbol] = tuple(
            Bar(
                timestamp=_as_utc(row.timestamp),
                open=row.open,
                high=row.high,
                low=row.low,
                close=row.close,
                volume=row.volume,
                instrument_id=symbol,
                data_quality=row.data_quality,
            )
            for row in rows
        )
        distinct = {row.manifest_checksum for row in rows}
        if len(distinct) != 1:
            raise RuntimeError(f"{symbol} range mixes data revisions: {sorted(distinct)}")
        checksums[symbol] = distinct.pop()
    manifests = list(
        session.scalars(
            select(DataManifestRecord).where(
                DataManifestRecord.checksum.in_(sorted(set(checksums.values())))
            )
        )
    )
    manifest_by_checksum = {manifest.checksum: manifest.id for manifest in manifests}
    missing = set(checksums.values()) - set(manifest_by_checksum)
    if missing:
        raise RuntimeError(f"data manifests missing for checksums: {sorted(missing)}")
    return output, [manifest_by_checksum[value] for value in checksums.values()], checksums


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return _as_utc(value).isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_json_value(item) for item in value]
    return value


def _metrics_json(metrics: BacktestMetrics) -> dict[str, Any]:
    converted = _json_value(asdict(metrics))
    if not isinstance(converted, dict):
        raise TypeError("serialised metrics must be a mapping")
    return converted


def _downsample[T](values: Sequence[T], maximum: int = 1200) -> tuple[T, ...]:
    if len(values) <= maximum:
        return tuple(values)
    step = max(1, len(values) // (maximum - 1))
    sampled = list(values[::step])
    if sampled[-1] is not values[-1]:
        sampled.append(values[-1])
    return tuple(sampled)


def _decision_context(result: PortfolioBacktestResult) -> dict[str, dict[str, Any]]:
    latest_candidate: dict[tuple[datetime, str], dict[str, Any]] = {}
    latest_challenge: dict[tuple[datetime, str], dict[str, Any]] = {}
    contexts: dict[str, dict[str, Any]] = {}
    for event in result.audit_trail:
        instrument = str(event.details.get("instrument_id", ""))
        key = (event.timestamp, instrument)
        if event.event_type == "CANDIDATE_CREATED":
            latest_candidate[key] = dict(event.details)
        elif event.event_type == "CANDIDATE_CHALLENGED":
            latest_challenge[key] = dict(event.details)
        elif event.event_type == "RISK_DECISION":
            decision_id = str(event.details.get("decision_id", ""))
            contexts[decision_id] = {
                "candidate": latest_candidate.get(key, {}),
                "challenge": latest_challenge.get(key, {}),
                "risk": dict(event.details),
            }
    return contexts


def _opportunity_groups(
    result: PortfolioBacktestResult,
) -> Iterable[tuple[datetime, dict[str, Any], dict[str, Any], dict[str, Any]]]:
    challenges: dict[tuple[datetime, str], dict[str, Any]] = {}
    risks: dict[tuple[datetime, str], dict[str, Any]] = {}
    candidates: list[tuple[datetime, dict[str, Any]]] = []
    for event in result.audit_trail:
        instrument = str(event.details.get("instrument_id", ""))
        key = (event.timestamp, instrument)
        if event.event_type == "CANDIDATE_CREATED":
            candidates.append((event.timestamp, dict(event.details)))
        elif event.event_type == "CANDIDATE_CHALLENGED":
            challenges[key] = dict(event.details)
        elif event.event_type == "RISK_DECISION":
            risks[key] = dict(event.details)
    for timestamp, candidate in candidates:
        key = (timestamp, str(candidate.get("instrument_id", "")))
        yield timestamp, candidate, challenges.get(key, {}), risks.get(key, {})


def _strategy_version_label(versions: Mapping[str, str]) -> str:
    """Return a compact database label while preserving the full mapping elsewhere.

    The service appends an instrument identifier to each strategy version so
    audit records remain unambiguous. Joining those identifiers exceeds the
    64-character ``backtests.strategy_version`` column for a normal
    multi-market run on PostgreSQL. Strip only the known instrument suffix;
    the complete per-instrument values are retained in ``configuration``.
    """

    compact = sorted(
        {version.removesuffix(f":{instrument_id}") for instrument_id, version in versions.items()}
    )
    label = ";".join(compact)
    if len(label) <= 64:
        return label
    digest = hashlib.sha256(
        json.dumps(dict(sorted(versions.items())), separators=(",", ":")).encode()
    ).hexdigest()[:16]
    return f"strategy-set-{digest}"


def _persist_result(
    session: Session,
    request: BacktestRunRequest,
    result: PortfolioBacktestResult,
    manifest_ids: list[str],
    checksums: dict[str, str],
) -> BacktestRecord:
    now = datetime.now(UTC)
    record = BacktestRecord(
        name=request.name,
        strategy=request.strategy,
        strategy_version=_strategy_version_label(result.strategy_versions),
        status="COMPLETED",
        created_at=now,
        started_at=now,
        completed_at=now,
        starting_equity=result.metrics.starting_equity,
        final_equity=result.metrics.final_equity,
        configuration={
            "date_range": f"{request.start.isoformat()} / {request.end.isoformat()}",
            "date_from": request.start.isoformat(),
            "date_to": request.end.isoformat(),
            "symbols": list(request.symbols),
            "provider_symbols": {
                symbol: CORE_UNIVERSE[symbol].provider_symbol for symbol in request.symbols
            },
            "resolution": request.interval,
            "risk_profile": request.risk_profile.value,
            "cost_model": request.cost_preset.value,
            "fill_policy": FillPolicy.CONSERVATIVE.value,
            "compounding": True,
            "lookahead_guard": True,
            "risk_taper": request.risk_taper,
            "seed": request.seed,
            "maximum_holding_bars": request.maximum_holding_bars,
            "strategy_versions": dict(sorted(result.strategy_versions.items())),
            "static_quote_to_gbp": {
                symbol: str(_CONVERSION_TO_GBP.get(CORE_UNIVERSE[symbol].currency, 1))
                for symbol in request.symbols
            },
        },
        metrics=_metrics_json(result.metrics),
        result_payload={},
        data_manifest_ids=manifest_ids,
        reproducibility_hash=result.run_fingerprint,
    )
    session.add(record)
    session.flush()
    ledger_timestamp = result.equity_curve[0].timestamp if result.equity_curve else request.start
    session.add(
        ManagedCapitalLedgerRecord(
            portfolio_id=record.id,
            timestamp=ledger_timestamp,
            entry_type="INITIAL_CAPITAL",
            amount=result.metrics.starting_equity,
            balance=result.metrics.starting_equity,
            reference_id=record.id,
            metadata_json={"backtest_id": record.id, "source": "HISTORICAL"},
        )
    )

    contexts = _decision_context(result)
    for trade in result.trades:
        context = contexts.get(trade.risk_decision_id, {})
        order_intent_id = hashlib.sha256(f"{record.id}|{trade.trade_id}".encode()).hexdigest()[:36]
        session.add(
            TradeRecord(
                backtest_id=record.id,
                order_intent_id=order_intent_id,
                instrument=trade.instrument_id,
                strategy=trade.strategy_version_id,
                direction=trade.direction.value,
                opened_at=trade.entry_timestamp,
                closed_at=trade.exit_timestamp,
                entry_price=trade.actual_entry,
                exit_price=trade.actual_exit,
                size=trade.quantity,
                stop_price=trade.stop_price,
                target_price=trade.target_price,
                gross_pnl=trade.gross_pnl,
                net_pnl=trade.net_pnl,
                total_cost=trade.total_cost,
                equity_before=trade.managed_equity_before,
                equity_after=trade.managed_equity_after,
                regime=trade.regime,
                audit={"trade": _json_value(asdict(trade)), **context},
            )
        )
        session.add(
            ManagedCapitalLedgerRecord(
                portfolio_id=record.id,
                timestamp=trade.exit_timestamp,
                entry_type="REALISED_PNL",
                amount=trade.net_pnl,
                balance=trade.managed_equity_after,
                reference_id=trade.trade_id,
                metadata_json={
                    "backtest_id": record.id,
                    "instrument": trade.instrument_id,
                    "source": "HISTORICAL",
                },
            )
        )
        session.add(
            AuditEventRecord(
                timestamp=trade.exit_timestamp,
                category="BROKER",
                severity="INFO",
                message=f"historical position closed: {trade.instrument_id}",
                details={
                    "backtest_id": record.id,
                    "trade_id": trade.trade_id,
                    "net_pnl": str(trade.net_pnl),
                    "equity_after": str(trade.managed_equity_after),
                },
            )
        )

    if result.metrics.operational_costs > 0:
        session.add(
            ManagedCapitalLedgerRecord(
                portfolio_id=record.id,
                timestamp=(
                    result.equity_curve[-1].timestamp if result.equity_curve else request.end
                ),
                entry_type="OPERATIONAL_COST",
                amount=-result.metrics.operational_costs,
                balance=result.metrics.final_equity,
                reference_id=record.id,
                metadata_json={"backtest_id": record.id, "source": "HISTORICAL"},
            )
        )

    for timestamp, candidate, challenge, risk in _opportunity_groups(result):
        approved = bool(challenge.get("approved")) and bool(risk.get("approved"))
        reasons = list(challenge.get("rejection_reasons", [])) + list(risk.get("reasons", []))
        instrument_id = str(candidate["instrument_id"])
        candidate_payload = {
            **candidate,
            "data_versions": {
                "market_data_checksum": checksums.get(instrument_id),
                "backtest_reproducibility_hash": result.run_fingerprint,
            },
            "model_versions": {
                "strategy": result.strategy_versions.get(instrument_id),
                "challenger": "DeterministicChallenger",
                "risk_engine": "RiskEngine",
            },
        }
        session.add(
            OpportunityRecord(
                backtest_id=record.id,
                timestamp=timestamp,
                instrument=instrument_id,
                strategy=str(candidate["strategy_version_id"]),
                direction=str(candidate["direction"]),
                raw_score=Decimal(str(candidate["raw_score"])),
                expected_growth_score=Decimal(str(candidate["expected_growth_score"])),
                approved=approved,
                rejection_reasons=reasons,
                candidate=candidate_payload,
                challenge=challenge,
                risk_decision=risk,
            )
        )
    session.flush()
    record.result_payload = serialize_backtest(record, result, checksums)
    session.commit()
    return record


def _trade_return_fractions(result: PortfolioBacktestResult) -> tuple[Decimal, ...]:
    return tuple(
        trade.net_pnl / trade.managed_equity_before
        for trade in result.trades
        if trade.managed_equity_before > 0
    )


def _monte_carlo(result: PortfolioBacktestResult) -> dict[str, float]:
    returns = _trade_return_fractions(result)
    if not returns:
        start = float(result.metrics.starting_equity)
        return {
            "percentile5": start,
            "percentile25": start,
            "median": start,
            "percentile75": start,
            "percentile95": start,
            "belowStartingProbability": 0.0,
            "ruinProbability": 0.0,
            "target750Probability": 0.0,
            "target1000Probability": 0.0,
            "target5000Probability": 0.0,
        }
    analysis = TradeSequenceMonteCarlo().run(
        returns,
        starting_equity=result.metrics.starting_equity,
        simulations=1000,
        seed=result.config.seed,
    )
    return {
        "percentile5": float(analysis.percentile_5),
        "percentile25": float(analysis.percentile_25),
        "median": float(analysis.median_final_equity),
        "percentile75": float(analysis.percentile_75),
        "percentile95": float(analysis.percentile_95),
        "belowStartingProbability": float(analysis.probability_below_start * 100),
        "ruinProbability": float(analysis.probability_of_ruin * 100),
        "target750Probability": float(analysis.target_probabilities["750"] * 100),
        "target1000Probability": float(analysis.target_probabilities["1000"] * 100),
        "target5000Probability": float(analysis.target_probabilities["5000"] * 100),
    }


def _stress_results(result: PortfolioBacktestResult) -> list[dict[str, Any]]:
    returns = _trade_return_fractions(result)
    if not returns:
        return []
    output = []
    for scenario in STANDARD_STRESS_SCENARIOS:
        stressed = apply_stress(returns, scenario, seed=result.config.seed)
        equity = result.metrics.starting_equity
        for value in stressed:
            equity *= Decimal("1") + value
        output.append(
            {
                "scenario": scenario.name,
                "trades": len(stressed),
                "finalEquity": float(equity),
                "returnPercent": float(
                    (equity / result.metrics.starting_equity - Decimal("1")) * 100
                ),
            }
        )
    return output


def _group_rows(
    trades: Sequence[Any], attribute: str, starting_equity: Decimal
) -> list[dict[str, Any]]:
    groups: dict[str, list[Any]] = {}
    for trade in trades:
        groups.setdefault(str(getattr(trade, attribute)), []).append(trade)
    return [
        {
            "label": label,
            "trades": len(items),
            "returnPercent": float(
                sum((trade.net_pnl for trade in items), Decimal("0")) / starting_equity * 100
            ),
            "pnl": float(sum((trade.net_pnl for trade in items), Decimal("0"))),
            "winRate": float(
                Decimal(sum(trade.net_pnl > 0 for trade in items)) / Decimal(len(items)) * 100
            ),
        }
        for label, items in sorted(groups.items())
    ]


def _ui_metrics(metrics: BacktestMetrics) -> dict[str, Any]:
    total_costs = (
        metrics.spread_cost + metrics.slippage_cost + metrics.financing_cost + metrics.commission
    )
    return {
        "startingEquity": float(metrics.starting_equity),
        "finalEquity": float(metrics.final_equity),
        "totalReturn": float(metrics.total_return * 100),
        "cagr": float((metrics.cagr or Decimal("0")) * 100),
        "maximumDrawdown": float(metrics.maximum_drawdown * 100),
        "drawdownDuration": f"{metrics.drawdown_duration_seconds / 86400:.1f} days",
        "trades": metrics.number_of_trades,
        "winRate": float(metrics.win_rate * 100),
        "averageWinner": float(metrics.average_winner),
        "averageLoser": float(metrics.average_loser),
        "profitFactor": float(metrics.profit_factor or 0),
        "expectancy": float(metrics.expectancy),
        "sharpe": float(metrics.sharpe_ratio or 0),
        "sortino": float(metrics.sortino_ratio or 0),
        "calmar": float(metrics.calmar_ratio or 0),
        "exposure": float(metrics.exposure_percentage * 100),
        "averageLeverage": float(metrics.average_effective_leverage),
        "maxLeverage": float(metrics.maximum_effective_leverage),
        "totalCosts": float(total_costs),
    }


def _regime(value: str) -> str:
    supported = {
        "TRENDING_UP",
        "TRENDING_DOWN",
        "RANGING",
        "HIGH_VOLATILITY",
        "LOW_VOLATILITY",
        "RISK_ON",
        "RISK_OFF",
        "UNKNOWN",
    }
    return value if value in supported else "UNKNOWN"


def serialize_opportunity(record: OpportunityRecord) -> dict[str, Any]:
    candidate = record.candidate
    challenge = record.challenge
    risk = record.risk_decision
    components = candidate.get("score_components") or {}
    factors = [
        {
            "label": key.replace("_", " ").title(),
            "value": float(value),
            "contribution": float(value) * 100,
            "tone": "negative" if "penalty" in key else "positive",
            "detail": f"Deterministic score component: {value}",
        }
        for key, value in components.items()
        if key != "total"
    ]
    explanation_data = candidate.get("explanation") or {}
    explanation = str(
        explanation_data.get("signal")
        or explanation_data.get("ensemble_selected")
        or "Inspect the stored structured candidate evidence."
    )
    risk_approved = bool(risk.get("approved"))
    challenge_approved = bool(challenge.get("approved"))
    return {
        "id": record.id,
        "timestamp": _as_utc(record.timestamp).isoformat(),
        "instrument": DISPLAY_NAMES.get(record.instrument, record.instrument),
        "marketFamily": CORE_UNIVERSE[record.instrument].asset_class,
        "direction": record.direction,
        "strategy": record.strategy.split(":", 1)[0],
        "strategyVersion": record.strategy,
        "score": float(record.expected_growth_score * 100),
        "originalScore": float(Decimal(str(challenge.get("original_score", 0))) * 100),
        "status": "ELIGIBLE" if record.approved else "REJECTED",
        "signalPrice": float(candidate.get("signal_price", 0)),
        "expectedHorizon": (f"{int(candidate.get('expected_horizon_seconds', 0)) / 3600:g} hours"),
        "calibratedProbability": (
            None
            if candidate.get("calibrated_probability") is None
            else float(candidate["calibrated_probability"])
        ),
        "expectedUpside": float(candidate.get("expected_upside", 0)) * 100,
        "expectedDownside": float(candidate.get("expected_downside", 0)) * 100,
        "rewardRiskRatio": float(candidate.get("reward_risk_ratio", 0)),
        "estimatedTotalCost": float(candidate.get("estimated_total_cost", 0)) * 100,
        "regime": _regime(str(candidate.get("regime", "UNKNOWN"))),
        "factors": factors,
        "explanation": explanation,
        "rejectionReasons": list(record.rejection_reasons),
        "approvedByChallenger": challenge_approved,
        "riskDecision": "APPROVED" if risk_approved else ("REJECTED" if risk else "NOT_EVALUATED"),
        "proposedRisk": (
            float(
                Decimal(str(risk.get("planned_monetary_risk", 0)))
                / Decimal(str(risk.get("equity_basis", 1)))
                * 100
            )
            if Decimal(str(risk.get("equity_basis", 0))) > 0
            else 0.0
        ),
    }


def _trade_payload(trade: Any, context: dict[str, Any]) -> dict[str, Any]:
    challenge = context.get("challenge", {})
    risk = context.get("risk", {})
    candidate = context.get("candidate", {})
    explanation_data = candidate.get("explanation") or {}
    return {
        "id": trade.trade_id,
        "instrument": DISPLAY_NAMES.get(trade.instrument_id, trade.instrument_id),
        "direction": trade.direction.value,
        "strategy": trade.strategy_version_id.split(":", 1)[0],
        "strategyVersion": trade.strategy_version_id,
        "openedAt": trade.entry_timestamp.isoformat(),
        "closedAt": trade.exit_timestamp.isoformat(),
        "entryPrice": float(trade.actual_entry),
        "exitPrice": float(trade.actual_exit),
        "stopPrice": float(trade.stop_price),
        "targetPrice": float(trade.target_price or 0),
        "size": float(trade.quantity),
        "grossPnl": float(trade.gross_pnl),
        "netPnl": float(trade.net_pnl),
        "costs": {
            "spread": float(trade.spread_cost),
            "slippage": float(trade.slippage_cost),
            "financing": float(trade.financing_cost),
            "commission": float(trade.commission),
        },
        "opportunityScore": float(trade.opportunity_score * 100),
        "challengeResult": "APPROVED" if challenge.get("approved") else "REJECTED",
        "riskDecision": "APPROVED" if risk.get("approved") else "REJECTED",
        "explanation": str(
            explanation_data.get("signal") or explanation_data.get("ensemble_selected") or ""
        ),
        "exitReason": trade.exit_reason.value,
        "regime": _regime(trade.regime),
        "managedEquityBefore": float(trade.managed_equity_before),
        "managedEquityAfter": float(trade.managed_equity_after),
        "mae": float(trade.maximum_adverse_excursion),
        "mfe": float(trade.maximum_favourable_excursion),
    }


def serialize_backtest(
    record: BacktestRecord,
    result: PortfolioBacktestResult,
    checksums: dict[str, str],
) -> dict[str, Any]:
    sampled = _downsample(result.equity_curve)
    contexts = _decision_context(result)
    opportunities = [
        serialize_opportunity(item) for item in record.opportunities if not item.approved
    ]
    config = record.configuration
    return {
        "id": record.id,
        "name": record.name,
        "status": record.status,
        "progress": 100,
        "createdAt": _as_utc(record.created_at).isoformat(),
        "startedAt": _as_utc(record.started_at or record.created_at).isoformat(),
        "completedAt": _as_utc(record.completed_at or record.created_at).isoformat(),
        "dataSource": "Yahoo Finance chart API · research-only cached download",
        "dataQuality": "Validated; gaps remain explicit and are not filled",
        "dataChecksums": checksums,
        "symbols": [DISPLAY_NAMES.get(symbol, symbol) for symbol in config["symbols"]],
        "dateFrom": config["date_from"],
        "dateTo": config["date_to"],
        "resolution": config["resolution"],
        "strategy": record.strategy,
        "riskProfile": config["risk_profile"],
        "costModel": config["cost_model"],
        "compounding": True,
        "riskTaper": bool(config["risk_taper"]),
        "seed": config["seed"],
        "metrics": _ui_metrics(result.metrics),
        "equityCurve": [
            {"timestamp": point.timestamp.isoformat(), "value": float(point.equity)}
            for point in sampled
        ],
        "drawdownCurve": [
            {"timestamp": point.timestamp.isoformat(), "value": float(point.drawdown * 100)}
            for point in sampled
        ],
        "exposureCurve": [
            {
                "timestamp": point.timestamp.isoformat(),
                "value": float(point.exposure / point.equity * 100) if point.equity > 0 else 0,
            }
            for point in sampled
        ],
        "trades": [
            _trade_payload(trade, contexts.get(trade.risk_decision_id, {}))
            for trade in result.trades
        ],
        "rejectedOpportunities": opportunities[-500:],
        "monthlyReturns": [
            {"period": key, "value": float(value * 100)}
            for key, value in result.metrics.monthly_returns.items()
        ],
        "annualReturns": [
            {"period": key, "value": float(value * 100)}
            for key, value in result.metrics.annual_returns.items()
        ],
        "instrumentBreakdown": _group_rows(
            result.trades, "instrument_id", result.metrics.starting_equity
        ),
        "regimeBreakdown": _group_rows(result.trades, "regime", result.metrics.starting_equity),
        "strategyBreakdown": _group_rows(
            result.trades, "strategy_version_id", result.metrics.starting_equity
        ),
        "monteCarlo": _monte_carlo(result),
        "milestones": {
            key: value.first_exceeded.isoformat() if value.first_exceeded else None
            for key, value in result.metrics.milestones.items()
        },
        "stressScenarios": _stress_results(result),
        "reproducibilityHash": result.run_fingerprint,
        "ordersByInstrument": result.orders_by_instrument,
        "rejectedCandidateCount": result.rejected_candidates,
        "_replay": {
            "equityCurve": [
                {
                    "timestamp": point.timestamp.isoformat(),
                    "equity": float(point.equity),
                    "exposure": float(point.exposure),
                }
                for point in result.equity_curve
            ],
            "auditTrail": [
                {
                    "sequence": event.sequence,
                    "timestamp": event.timestamp.isoformat(),
                    "eventType": event.event_type,
                    "details": event.details,
                }
                for event in result.audit_trail
                if event.event_type != "MARKET_BAR_COMPLETED"
            ],
        },
    }


def execute_backtest(session: Session, request: BacktestRunRequest) -> BacktestRecord:
    bars, manifest_ids, checksums = _load_bars(session, request)
    instruments = {symbol: _instrument(symbol) for symbol in request.symbols}
    strategies = {symbol: _strategy(request.strategy, symbol) for symbol in request.symbols}
    engine = PortfolioBacktestEngine(
        instruments,
        strategies,
        risk_limits=limits_for_profile(request.risk_profile),
        risk_taper=request.risk_taper,
    )
    result = engine.run(
        bars,
        BacktestConfig(
            starting_equity=request.starting_equity,
            cost_preset=request.cost_preset,
            fill_policy=FillPolicy.CONSERVATIVE,
            execution_delay_bars=1,
            maximum_holding_bars=request.maximum_holding_bars,
            operational_costs=request.operational_costs,
            seed=request.seed,
        ),
    )
    return _persist_result(session, request, result, manifest_ids, checksums)


def execute_cash_baseline(session: Session, request: BacktestRunRequest) -> BacktestRecord:
    bars, manifest_ids, checksums = _load_bars(session, request)
    timestamps = sorted({bar.timestamp for values in bars.values() for bar in values})
    points = (
        EquityPoint(timestamps[0], request.starting_equity, request.starting_equity, Decimal("0")),
        EquityPoint(timestamps[-1], request.starting_equity, request.starting_equity, Decimal("0")),
    )
    config = BacktestConfig(
        starting_equity=request.starting_equity,
        cost_preset=request.cost_preset,
        maximum_holding_bars=request.maximum_holding_bars,
        seed=request.seed,
    )
    fingerprint = hashlib.sha256(
        json.dumps(
            {"cash": True, "checksums": checksums, "config": _json_value(asdict(config))},
            sort_keys=True,
        ).encode()
    ).hexdigest()
    result = PortfolioBacktestResult(
        run_fingerprint=fingerprint,
        config=config,
        strategy_versions={symbol: "cash-v1" for symbol in request.symbols},
        trades=(),
        equity_curve=points,
        audit_trail=(),
        metrics=calculate_metrics(request.starting_equity, (), points),
        rejected_candidates=0,
        broker_orders_submitted=0,
        orders_by_instrument={symbol: 0 for symbol in request.symbols},
    )
    cash_request = replace(request, name="Cash baseline", strategy="Quant Baseline")
    record = _persist_result(session, cash_request, result, manifest_ids, checksums)
    record.strategy = "Cash baseline"
    record.strategy_version = "cash-v1"
    record.result_payload["name"] = "Cash baseline"
    record.result_payload["strategy"] = "Cash baseline"
    session.commit()
    return record


def latest_backtest_payload(session: Session) -> dict[str, Any] | None:
    record = session.scalar(
        select(BacktestRecord)
        .where(BacktestRecord.status == "COMPLETED")
        .order_by(desc(BacktestRecord.completed_at), desc(BacktestRecord.created_at))
        .limit(1)
    )
    if not record or not record.result_payload:
        return None
    return {key: value for key, value in record.result_payload.items() if not key.startswith("_")}
