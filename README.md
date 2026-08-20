# Trading Intelligence Platform

A local, deterministic multi-market research platform with an internal **£500 managed-capital ledger**, event-driven historical simulation, realistic trading costs, and a strictly Demo-only IG integration. Live execution is deliberately absent and cannot be enabled in V1.

This software is for research and IG Demo experimentation, not financial advice. Public historical data is research-only and not broker-grade. Losses, gaps, latency and costs can be materially worse than historical simulation.

## Secure local setup

```bash
git clone https://github.com/ian8500/trading.git
cd trading
cp .env.example .env
chmod 600 .env
make setup
make dev
```

The dashboard is served only on [http://localhost:5173](http://localhost:5173), and the backend health endpoint is [http://localhost:8000/api/v1/health](http://localhost:8000/api/v1/health). The app starts without IG, AI, news, or macro credentials.

`make dev` starts the Compose stack in the background. Use `make logs` to follow it and `make stop` to stop it. The example database URL uses `127.0.0.1` for host-side import/backtest commands; Compose safely overrides that hostname to its internal `db` service for the backend container.

Never paste IG credentials into GitHub, Codex prompts, issues, documentation, or chat messages. Create a fresh IG Demo API key and enter it only in the local `.env` file.

## Verification and research

```bash
make test
make lint
make typecheck
make secret-scan
make data-real
make backtest-real
make research-protocol
make backtest-smoke
make stop
```

Downloaded market data and exported results are deliberately ignored by Git. See `BACKTESTING.md`, `DATA_SOURCES.md`, `RISK.md`, `SECURITY.md`, and `IG_INTEGRATION.md` for exact assumptions and limitations.

The checked-in [`docs/FIRST_BACKTEST_REPORT.md`](docs/FIRST_BACKTEST_REPORT.md) records the original
genuine-data, static-conversion first pass. The frozen protocol and its strict promotion gates are
defined in [`docs/RESEARCH_PROTOCOL.md`](docs/RESEARCH_PROTOCOL.md); hardened results are recorded
in [`docs/HARDENED_RESEARCH_REPORT.md`](docs/HARDENED_RESEARCH_REPORT.md) so the original evidence
is not silently rewritten. Provider bars and generated exports remain local-only.

No open-source licence is granted by this repository.
