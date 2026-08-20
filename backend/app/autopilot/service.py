"""Automatic, non-executing decisions from frozen research evidence.

The autopilot deliberately has no broker dependency and no order method.  It
continuously validates the latest frozen research artifact and converts that
evidence into a simple fail-closed recommendation for the dashboard.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from app.research.protocol import FROZEN_PROTOCOL, RETROSPECTIVE_LABEL
from app.research.provenance import load_strategy_implementation_provenance

AUTOPILOT_REFRESH_SECONDS = 60
DEFAULT_REPORT_PATH = Path("data/exports/research-protocol.json")


@dataclass(frozen=True, slots=True)
class AutopilotStrategyStatus:
    name: str
    status: str
    return_percent: float
    profit_factor: float
    trades: int
    maximum_drawdown_percent: float
    unmet_gate_count: int


@dataclass(frozen=True, slots=True)
class AutopilotSnapshot:
    mode: str
    state: str
    headline: str
    summary: str
    checked_at: str
    next_check_at: str
    refresh_seconds: int
    automatic_monitoring: bool
    evidence_status: str
    evidence_generated_at: str | None
    protocol_version: str
    protocol_fingerprint: str
    report_fingerprint: str | None
    implementation_digest: str
    strategies: tuple[AutopilotStrategyStatus, ...]
    reasons: tuple[str, ...]
    safeguards: tuple[str, ...]
    demo_trading_enabled: bool = False
    live_trading_enabled: bool = False
    order_execution_enabled: bool = False

    def to_payload(self) -> dict[str, object]:
        payload = asdict(self)
        return {
            "mode": payload["mode"],
            "state": payload["state"],
            "headline": payload["headline"],
            "summary": payload["summary"],
            "checkedAt": payload["checked_at"],
            "nextCheckAt": payload["next_check_at"],
            "refreshSeconds": payload["refresh_seconds"],
            "automaticMonitoring": payload["automatic_monitoring"],
            "evidenceStatus": payload["evidence_status"],
            "evidenceGeneratedAt": payload["evidence_generated_at"],
            "protocolVersion": payload["protocol_version"],
            "protocolFingerprint": payload["protocol_fingerprint"],
            "reportFingerprint": payload["report_fingerprint"],
            "implementationDigest": payload["implementation_digest"],
            "strategies": [
                {
                    "name": item["name"],
                    "status": item["status"],
                    "returnPercent": item["return_percent"],
                    "profitFactor": item["profit_factor"],
                    "trades": item["trades"],
                    "maximumDrawdownPercent": item["maximum_drawdown_percent"],
                    "unmetGateCount": item["unmet_gate_count"],
                }
                for item in payload["strategies"]
            ],
            "reasons": list(payload["reasons"]),
            "safeguards": list(payload["safeguards"]),
            "demoTradingEnabled": payload["demo_trading_enabled"],
            "liveTradingEnabled": payload["live_trading_enabled"],
            "orderExecutionEnabled": payload["order_execution_enabled"],
        }


def _decimal(value: object) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("research artifact contains an invalid numeric value") from exc


def _safe_snapshot(now: datetime, evidence_status: str, reason: str) -> AutopilotSnapshot:
    implementation = load_strategy_implementation_provenance()
    return AutopilotSnapshot(
        mode="SAFE_RESEARCH_AUTOPILOT",
        state="STAY_IN_CASH",
        headline="Stay in cash",
        summary="Verified evidence is unavailable, so the automatic decision is to take no action.",
        checked_at=now.isoformat(),
        next_check_at=(now + timedelta(seconds=AUTOPILOT_REFRESH_SECONDS)).isoformat(),
        refresh_seconds=AUTOPILOT_REFRESH_SECONDS,
        automatic_monitoring=True,
        evidence_status=evidence_status,
        evidence_generated_at=None,
        protocol_version=FROZEN_PROTOCOL.protocol_version,
        protocol_fingerprint=FROZEN_PROTOCOL.fingerprint,
        report_fingerprint=None,
        implementation_digest=implementation.digest,
        strategies=(),
        reasons=(reason, "Fail-closed policy requires verified evidence before any escalation."),
        safeguards=(
            "No broker orders can be created by research autopilot.",
            "IG Demo remains stopped.",
            "Live execution remains unavailable.",
        ),
    )


def evaluate_artifact(artifact: object, *, now: datetime | None = None) -> AutopilotSnapshot:
    """Validate a serialized protocol report and derive a safe decision."""

    checked_at = now or datetime.now(UTC)
    try:
        if not isinstance(artifact, dict):
            raise ValueError("research artifact must be a JSON object")
        report = artifact.get("report")
        if not isinstance(report, dict):
            raise ValueError("research artifact has no report")
        canonical_fingerprint = artifact.get("canonicalReportFingerprint")
        if not isinstance(canonical_fingerprint, str) or len(canonical_fingerprint) != 64:
            raise ValueError("research artifact has no canonical report identity")
        if report.get("report_fingerprint") != canonical_fingerprint:
            raise ValueError("research artifact envelope and report identities differ")
        if report.get("label") != RETROSPECTIVE_LABEL:
            raise ValueError("research artifact disclosure label is invalid")
        if report.get("protocol_version") != FROZEN_PROTOCOL.protocol_version:
            raise ValueError("research artifact protocol version is stale")
        if report.get("protocol_fingerprint") != FROZEN_PROTOCOL.fingerprint:
            raise ValueError("research artifact protocol identity is stale")

        provenance = report.get("strategy_implementation_provenance")
        implementation = load_strategy_implementation_provenance()
        if not isinstance(provenance, dict) or provenance.get("digest") != implementation.digest:
            raise ValueError("research artifact strategy implementation is stale")

        raw_results = report.get("strategy_results")
        if not isinstance(raw_results, list) or not raw_results:
            raise ValueError("research artifact contains no strategy results")
        strategies: list[AutopilotStrategyStatus] = []
        promotion_allowed = False
        for raw in raw_results:
            if not isinstance(raw, dict):
                raise ValueError("research artifact strategy result is invalid")
            verdict = raw.get("verdict")
            aggregate = raw.get("test_aggregate")
            if not isinstance(verdict, dict) or not isinstance(aggregate, dict):
                raise ValueError("research artifact strategy evidence is incomplete")
            unmet_gates = verdict.get("unmet_gates")
            if not isinstance(unmet_gates, list):
                raise ValueError("research artifact gate evidence is invalid")
            promotion_allowed = promotion_allowed or verdict.get("promotion_allowed") is True
            strategies.append(
                AutopilotStrategyStatus(
                    name=str(raw.get("strategy_name", "Unknown strategy")),
                    status=str(verdict.get("status", "NOT_ELIGIBLE")),
                    return_percent=float(_decimal(aggregate.get("after_cost_return")) * 100),
                    profit_factor=float(_decimal(aggregate.get("aggregate_profit_factor"))),
                    trades=int(aggregate.get("aggregate_trades", 0)),
                    maximum_drawdown_percent=float(
                        _decimal(aggregate.get("worst_fold_maximum_drawdown")) * 100
                    ),
                    unmet_gate_count=len(unmet_gates),
                )
            )

        generated_at = artifact.get("generatedAt")
        state = "HUMAN_REVIEW_REQUIRED" if promotion_allowed else "STAY_IN_CASH"
        headline = "Pause for human review" if promotion_allowed else "Stay in cash"
        summary = (
            "Research gates passed, but automatic execution remains blocked pending prospective "
            "evidence and human review."
            if promotion_allowed
            else "No tested strategy passed every after-cost safety gate, so taking no position is "
            "the sensible automatic decision."
        )
        reasons = (
            (
                "Frozen research evidence requires an explicit human promotion decision.",
                "Prospective and IG Demo evidence are still mandatory.",
            )
            if promotion_allowed
            else (
                "Every tested strategy is NOT_ELIGIBLE.",
                "Aggregate after-cost performance is negative for all tested strategies.",
                "Preserving capital takes priority over generating activity.",
            )
        )
        return AutopilotSnapshot(
            mode="SAFE_RESEARCH_AUTOPILOT",
            state=state,
            headline=headline,
            summary=summary,
            checked_at=checked_at.isoformat(),
            next_check_at=(checked_at + timedelta(seconds=AUTOPILOT_REFRESH_SECONDS)).isoformat(),
            refresh_seconds=AUTOPILOT_REFRESH_SECONDS,
            automatic_monitoring=True,
            evidence_status="VERIFIED",
            evidence_generated_at=str(generated_at) if generated_at else None,
            protocol_version=FROZEN_PROTOCOL.protocol_version,
            protocol_fingerprint=FROZEN_PROTOCOL.fingerprint,
            report_fingerprint=canonical_fingerprint,
            implementation_digest=implementation.digest,
            strategies=tuple(strategies),
            reasons=reasons,
            safeguards=(
                "Research autopilot cannot submit broker orders.",
                "IG Demo requires separate authenticated enablement and remains off.",
                "Live execution is unavailable in V1.",
            ),
        )
    except (KeyError, RuntimeError, TypeError, ValueError) as exc:
        return _safe_snapshot(checked_at, "INVALID", str(exc))


def load_snapshot(
    report_path: Path = DEFAULT_REPORT_PATH, *, now: datetime | None = None
) -> AutopilotSnapshot:
    checked_at = now or datetime.now(UTC)
    try:
        artifact: Any = json.loads(report_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _safe_snapshot(
            checked_at,
            "MISSING",
            "The frozen research report has not been generated in this environment.",
        )
    except (OSError, json.JSONDecodeError) as exc:
        return _safe_snapshot(checked_at, "INVALID", f"Research evidence could not be read: {exc}")
    return evaluate_artifact(artifact, now=checked_at)


class AutopilotMonitor:
    """Refresh a safe research decision while the backend is running."""

    def __init__(
        self,
        report_path: Path = DEFAULT_REPORT_PATH,
        refresh_seconds: int = AUTOPILOT_REFRESH_SECONDS,
    ) -> None:
        self.report_path = report_path
        self.refresh_seconds = refresh_seconds
        self._snapshot: AutopilotSnapshot | None = None
        self._task: asyncio.Task[None] | None = None

    def refresh(self) -> AutopilotSnapshot:
        self._snapshot = load_snapshot(self.report_path)
        return self._snapshot

    @property
    def snapshot(self) -> AutopilotSnapshot:
        return self._snapshot or self.refresh()

    async def start(self) -> None:
        if self._task is not None:
            return
        self.refresh()
        self._task = asyncio.create_task(self._run(), name="research-autopilot-monitor")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self.refresh_seconds)
            self.refresh()


autopilot_monitor = AutopilotMonitor()
