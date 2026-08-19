#!/bin/sh
set -eu

tracked_sensitive="$(mktemp -t trading-tracked-secrets.XXXXXX)"
report="$(mktemp -t trading-detect-secrets.XXXXXX)"
trap 'rm -f "$tracked_sensitive" "$report"' EXIT HUP INT TERM

git ls-files | awk '
  /(^|\/)\.env($|\.)/ && $0 !~ /(^|\/)\.env\.example$/ { print; next }
  /\.(pem|key|crt)$/ { print }
' >"$tracked_sensitive"
if [ -s "$tracked_sensitive" ]; then
  echo "Secret scan failed: sensitive file paths are tracked:" >&2
  sed 's/^/  /' "$tracked_sensitive" >&2
  exit 1
fi

if command -v gitleaks >/dev/null 2>&1 && git rev-parse --verify HEAD >/dev/null 2>&1; then
  gitleaks git . --config .gitleaks.toml --redact --no-banner
fi

if [ -x .venv/bin/detect-secrets ]; then
  .venv/bin/detect-secrets scan --all-files --force-use-all-plugins \
    --exclude-files '(^|/)(\.git|\.venv|venv|node_modules|dist|build|coverage|\.pytest_cache|\.mypy_cache|\.ruff_cache|[^/]+\.egg-info|data/(downloads|cache|historical|exports))/' \
    --exclude-files '(^|/)\.env($|\.)' >"$report"
  .venv/bin/python scripts/verify_secret_scan.py "$report"
  exit 0
fi

echo "Install project dev dependencies or gitleaks before running secret-scan" >&2
exit 1
