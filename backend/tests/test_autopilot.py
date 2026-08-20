from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from app.autopilot.service import evaluate_artifact, load_snapshot
from app.research.protocol import FROZEN_PROTOCOL, RETROSPECTIVE_LABEL
from app.research.provenance import load_strategy_implementation_provenance


def _artifact(*, promotion_allowed: bool = False, implementation_digest: str | None = None):
    provenance = load_strategy_implementation_provenance()
    report_fingerprint = "a" * 64
    return {
        "generatedAt": "2026-08-20T00:00:00+00:00",
        "canonicalReportFingerprint": report_fingerprint,
        "report": {
            "label": RETROSPECTIVE_LABEL,
            "protocol_version": FROZEN_PROTOCOL.protocol_version,
            "protocol_fingerprint": FROZEN_PROTOCOL.fingerprint,
            "report_fingerprint": report_fingerprint,
            "strategy_implementation_provenance": {
                "digest": implementation_digest or provenance.digest,
            },
            "strategy_results": [
                {
                    "strategy_name": "Quant Baseline",
                    "verdict": {
                        "status": (
                            "RESEARCH_GATES_PASSED_PROMOTION_BLOCKED"
                            if promotion_allowed
                            else "NOT_ELIGIBLE"
                        ),
                        "promotion_allowed": promotion_allowed,
                        "unmet_gates": [] if promotion_allowed else ["RETURN", "PROFIT_FACTOR"],
                    },
                    "test_aggregate": {
                        "after_cost_return": "-0.01" if not promotion_allowed else "0.02",
                        "aggregate_profit_factor": "0.9" if not promotion_allowed else "1.2",
                        "aggregate_trades": 55,
                        "worst_fold_maximum_drawdown": "0.08",
                    },
                }
            ],
        },
    }


def test_verified_losing_evidence_automatically_stays_in_cash() -> None:
    snapshot = evaluate_artifact(_artifact(), now=datetime(2026, 8, 20, 8, 0, tzinfo=UTC))

    assert snapshot.evidence_status == "VERIFIED"
    assert snapshot.state == "STAY_IN_CASH"
    assert snapshot.headline == "Stay in cash"
    assert snapshot.strategies[0].return_percent == -1.0
    assert snapshot.strategies[0].unmet_gate_count == 2
    assert snapshot.order_execution_enabled is False
    assert snapshot.demo_trading_enabled is False
    assert snapshot.live_trading_enabled is False


def test_passing_research_still_requires_human_review() -> None:
    snapshot = evaluate_artifact(_artifact(promotion_allowed=True))

    assert snapshot.evidence_status == "VERIFIED"
    assert snapshot.state == "HUMAN_REVIEW_REQUIRED"
    assert snapshot.order_execution_enabled is False


def test_stale_implementation_fails_closed() -> None:
    snapshot = evaluate_artifact(_artifact(implementation_digest="0" * 64))

    assert snapshot.evidence_status == "INVALID"
    assert snapshot.state == "STAY_IN_CASH"
    assert "stale" in snapshot.reasons[0].lower()
    assert snapshot.order_execution_enabled is False


def test_missing_artifact_fails_closed(tmp_path: Path) -> None:
    snapshot = load_snapshot(tmp_path / "missing-report.json")

    assert snapshot.evidence_status == "MISSING"
    assert snapshot.state == "STAY_IN_CASH"
    assert snapshot.strategies == ()
    assert snapshot.order_execution_enabled is False
