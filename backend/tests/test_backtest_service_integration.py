from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from app.api.routes.replay import _build_replay
from app.database.base import Base
from app.database.models import (
    BacktestRecord,
    HistoricalBarRecord,
    InstrumentRecord,
    OpportunityRecord,
)
from app.jobs.backtest_service import _strategy_version_label
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def test_multi_market_strategy_version_fits_database_column() -> None:
    versions = {
        symbol: f"quant-baseline-v1:{symbol}"
        for symbol in (
            "GBPUSD",
            "EURUSD",
            "USDJPY",
            "EURGBP",
            "FTSE100",
            "SP500",
            "NASDAQ100",
            "DAX",
            "GOLD",
        )
    }

    label = _strategy_version_label(versions)

    assert label == "quant-baseline-v1"
    assert len(label) <= 64


def test_long_strategy_set_uses_stable_bounded_label() -> None:
    versions = {f"market-{index}": f"version-{'x' * 60}-{index}" for index in range(3)}

    first = _strategy_version_label(versions)
    second = _strategy_version_label(dict(reversed(tuple(versions.items()))))

    assert first == second
    assert first.startswith("strategy-set-")
    assert len(first) <= 64


def _replay_record(timestamp: datetime) -> BacktestRecord:
    start = timestamp - timedelta(days=1)
    end = timestamp + timedelta(days=1)
    return BacktestRecord(
        name="Replay fixture",
        strategy="Quant Baseline",
        strategy_version="quant-baseline-v1",
        status="COMPLETED",
        created_at=timestamp,
        started_at=timestamp,
        completed_at=timestamp,
        starting_equity=Decimal("500"),
        final_equity=Decimal("501"),
        configuration={
            "symbols": ["GBPUSD"],
            "resolution": "1h",
            "date_from": start.isoformat(),
            "date_to": end.isoformat(),
            "risk_profile": "Standard",
            "cost_model": "REALISTIC",
        },
        metrics={},
        result_payload={
            "dataChecksums": {"GBPUSD": "pinned-revision"},
            "_replay": {
                "equityCurve": [{"timestamp": timestamp.isoformat(), "equity": 501, "exposure": 0}],
                "auditTrail": [],
            },
        },
        data_manifest_ids=[],
        reproducibility_hash="fixture",
    )


def _opportunity(backtest_id: str, timestamp: datetime, score: str) -> OpportunityRecord:
    return OpportunityRecord(
        backtest_id=backtest_id,
        timestamp=timestamp,
        instrument="GBPUSD",
        strategy="quant-baseline-v1:GBPUSD",
        direction="LONG",
        raw_score=Decimal(score),
        expected_growth_score=Decimal(score),
        approved=False,
        rejection_reasons=["fixture rejection"],
        candidate={
            "instrument_id": "GBPUSD",
            "strategy_version_id": "quant-baseline-v1:GBPUSD",
            "direction": "LONG",
            "raw_score": score,
            "expected_growth_score": score,
            "signal_price": "1.25",
            "expected_horizon_seconds": 3600,
            "calibrated_probability": None,
            "expected_upside": "0.01",
            "expected_downside": "0.005",
            "reward_risk_ratio": "2",
            "estimated_total_cost": "0.001",
            "regime": "TRENDING_UP",
            "score_components": {},
            "explanation": {"signal": "fixture"},
        },
        challenge={"approved": False, "original_score": score},
        risk_decision={},
    )


def test_replay_uses_pinned_bars_and_highest_ranked_candidate() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    timestamp = datetime(2025, 1, 2, 12, tzinfo=UTC)
    with Session(engine, expire_on_commit=False) as session:
        instrument = InstrumentRecord(
            symbol="GBPUSD",
            name="GBP/USD",
            asset_class="FX",
            currency="USD",
            provider_symbol="GBPUSD=X",
            ig_epic=None,
            active=True,
            capabilities={},
        )
        session.add(instrument)
        session.flush()
        record = _replay_record(timestamp)
        session.add(record)
        session.flush()
        for provider, checksum, close in (
            ("Yahoo Finance", "pinned-revision", "1.25"),
            ("Another provider", "different-revision", "999"),
        ):
            session.add(
                HistoricalBarRecord(
                    instrument_id=instrument.id,
                    provider=provider,
                    interval="1h",
                    timestamp=timestamp,
                    open=Decimal(close),
                    high=Decimal(close),
                    low=Decimal(close),
                    close=Decimal(close),
                    volume=Decimal("1"),
                    complete=True,
                    data_quality=Decimal("1"),
                    manifest_checksum=checksum,
                )
            )
        session.add_all(
            (
                _opportunity(record.id, timestamp, "0.70"),
                _opportunity(record.id, timestamp, "0.90"),
            )
        )
        session.commit()

        replay = _build_replay(session, record)

        assert replay["ticks"][0]["prices"] == {"GBP/USD": 1.25}  # type: ignore[index]
        assert replay["ticks"][0]["opportunity"]["score"] == 90.0  # type: ignore[index]


def test_replay_fails_closed_when_pinned_revision_is_unavailable() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    timestamp = datetime(2025, 1, 2, 12, tzinfo=UTC)
    with Session(engine, expire_on_commit=False) as session:
        session.add(
            InstrumentRecord(
                symbol="GBPUSD",
                name="GBP/USD",
                asset_class="FX",
                currency="USD",
                provider_symbol="GBPUSD=X",
                ig_epic=None,
                active=True,
                capabilities={},
            )
        )
        record = _replay_record(timestamp)
        session.add(record)
        session.commit()

        with pytest.raises(HTTPException, match="pinned replay data revision is unavailable"):
            _build_replay(session, record)
