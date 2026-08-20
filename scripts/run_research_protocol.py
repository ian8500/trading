"""Run the frozen retrospective protocol and write a non-database JSON artifact."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.database.session import SessionLocal
from app.jobs.backtest_service import _instrument, _strategy
from app.research.database_source import load_research_data
from app.research.evaluator import ResearchProtocolEvaluator
from app.research.models import json_value
from app.research.protocol import FROZEN_PROTOCOL


def run() -> dict[str, Any]:
    """Execute all three immutable strategies without persisting database rows."""

    with SessionLocal() as session:
        loaded = load_research_data(session, FROZEN_PROTOCOL)
        evaluator = ResearchProtocolEvaluator(
            bars_by_instrument=loaded.bars_by_instrument,
            data_snapshot=loaded.snapshot,
            instruments={symbol: _instrument(symbol) for symbol in FROZEN_PROTOCOL.symbols},
            strategy_factory=_strategy,
        )
        report = evaluator.evaluate()
    converted = json_value(report)
    if not isinstance(converted, dict):
        raise TypeError("research report must serialize to a JSON object")
    return {
        # This wall-clock field is explicitly outside every canonical hash.
        "generatedAt": datetime.now(UTC).isoformat(),
        "canonicalReportFingerprint": report.report_fingerprint,
        "report": converted,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the frozen RETROSPECTIVE_PSEUDO_OOS research protocol"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/exports/research-protocol.json"),
        help="ignored JSON artifact path (default: data/exports/research-protocol.json)",
    )
    args = parser.parse_args()
    artifact = run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report = artifact["report"]
    print(f"label={report['label']}")
    print(f"protocol={report['protocol_fingerprint']}")
    print(f"source={report['source_fingerprint']}")
    print(f"strategy_implementation={report['strategy_implementation_provenance']['digest']}")
    print(f"result={artifact['canonicalReportFingerprint']}")
    for result in report["strategy_results"]:
        verdict = result["verdict"]
        print(
            f"{result['strategy_name']}: {verdict['status']}; "
            f"unmet_gates={len(verdict['unmet_gates'])}; "
            f"sha256={result['result_fingerprint']}"
        )
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
