from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.database.session import SessionLocal
from app.instruments.catalog import OFFICIAL_DAILY_SYMBOLS, OFFICIAL_INTRADAY_SYMBOLS
from app.jobs.backtest_service import (
    BacktestRunRequest,
    execute_backtest,
    execute_cash_baseline,
)
from app.risk import RiskProfile


def _public(record: Any) -> dict[str, Any]:
    return {key: value for key, value in record.result_payload.items() if not key.startswith("_")}


def _daily_requests() -> tuple[BacktestRunRequest, ...]:
    def request(name: str, strategy: str, profile: RiskProfile) -> BacktestRunRequest:
        return BacktestRunRequest(
            name=name,
            strategy=strategy,
            symbols=OFFICIAL_DAILY_SYMBOLS,
            start=datetime(2018, 1, 1, tzinfo=UTC),
            end=datetime(2026, 8, 19, tzinfo=UTC),
            interval="1d",
            starting_equity=Decimal("500"),
            risk_profile=profile,
            maximum_holding_bars=2,
            seed=8500,
        )

    return (
        request("Quant Baseline · official daily", "Quant Baseline", RiskProfile.STANDARD),
        request("Quant Aggressive · official daily", "Quant Aggressive", RiskProfile.AGGRESSIVE),
        request("Regime Ensemble · official daily", "Regime Ensemble", RiskProfile.STANDARD),
    )


def _intraday_request() -> BacktestRunRequest:
    return BacktestRunRequest(
        name="Regime Ensemble · official hourly",
        strategy="Regime Ensemble",
        symbols=OFFICIAL_INTRADAY_SYMBOLS,
        start=datetime(2024, 8, 20, tzinfo=UTC),
        end=datetime(2026, 8, 19, tzinfo=UTC),
        interval="1h",
        starting_equity=Decimal("500"),
        risk_profile=RiskProfile.STANDARD,
        maximum_holding_bars=25,
        seed=8500,
    )


def _smoke_request() -> BacktestRunRequest:
    return BacktestRunRequest(
        name="Quant Baseline · local smoke",
        strategy="Quant Baseline",
        symbols=("GBPUSD", "SP500"),
        start=datetime(2025, 1, 1, tzinfo=UTC),
        end=datetime(2026, 1, 1, tzinfo=UTC),
        interval="1d",
        starting_equity=Decimal("500"),
        risk_profile=RiskProfile.STANDARD,
        maximum_holding_bars=2,
        seed=8500,
    )


def run(preset: str) -> dict[str, Any]:
    with SessionLocal() as session:
        if preset == "official-daily":
            requests = _daily_requests()
            cash = execute_cash_baseline(session, requests[0])
            completed = [execute_backtest(session, request) for request in requests]
            results = [_public(cash), *(_public(record) for record in completed)]
        elif preset == "official-intraday":
            results = [_public(execute_backtest(session, _intraday_request()))]
        elif preset == "smoke":
            results = [_public(execute_backtest(session, _smoke_request()))]
        else:
            raise ValueError(f"unknown preset: {preset}")
    return {
        "generatedAt": datetime.now(UTC).isoformat(),
        "preset": preset,
        "researchOnly": True,
        "startingManagedCapitalGbp": 500,
        "compounding": True,
        "lookaheadProtection": True,
        "costModel": "REALISTIC",
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run reproducible persisted research backtests")
    parser.add_argument(
        "--preset",
        choices=("official-daily", "official-intraday", "smoke"),
        default="official-daily",
    )
    parser.add_argument("--fixture", action="store_true", help="alias for the local smoke preset")
    parser.add_argument("--output", type=Path, default=Path("data/exports/backtest.json"))
    args = parser.parse_args()
    preset = "smoke" if args.fixture else args.preset
    report = run(preset)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for result in report["results"]:
        metrics = result["metrics"]
        print(
            f"{result['name']}: final=£{metrics['finalEquity']:.2f}, "
            f"return={metrics['totalReturn']:.2f}%, "
            f"drawdown={metrics['maximumDrawdown']:.2f}%, trades={metrics['trades']}, "
            f"sha256={result['reproducibilityHash']}"
        )
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
