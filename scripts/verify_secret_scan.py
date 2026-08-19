from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    report_path = Path(sys.argv[1])
    report = json.loads(report_path.read_text(encoding="utf-8"))
    findings = report.get("results", {})
    if findings:
        print(f"Secret scan failed: suspected secrets in {len(findings)} file(s); values redacted.")
        for filename in sorted(findings):
            print(f"  {filename}")
        return 1
    print("Secret scan passed (detect-secrets; no suspected secrets found).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
