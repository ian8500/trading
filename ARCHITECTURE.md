# Architecture

The platform is a Python-first modular monolith. The React dashboard is a client of one FastAPI process; PostgreSQL owns durable research, execution, ledger and audit state. Historical simulation, replay, and IG Demo execution share domain models for candidates, risk decisions, orders, fills and positions.

```text
completed market event
  -> feature/regime update
  -> deterministic strategies
  -> comparable OpportunityCandidate values
  -> ExpectedGrowthScore ranking
  -> deterministic Devil's Advocate
  -> authoritative RiskEngine
  -> broker interface (historical/simulated/IG Demo)
  -> fill and protected position
  -> chronological exit
  -> exact Decimal P&L and managed-capital ledger
  -> immutable audit record and dashboard API
```

## Safety boundaries

- Strategies, news, macro providers and AI can only propose candidates.
- The RiskEngine is the sole authority that can issue an approval consumed by a broker.
- Managed equity starts at £500 and is separate from the informational IG Demo account balance.
- The historical clock controls all market access; a strategy cannot read beyond simulated time.
- The IG client has a compiled Demo host allowlist. There is no V1 Live broker implementation.
- State-changing dashboard endpoints require a local administrator session and CSRF token.
- Credentials remain backend-only and are never included in public configuration or API schemas.

## Modules

`market_data` validates, caches and manifests provider bars. `strategies`, `regimes`, `opportunities`, `challenger`, `risk`, `portfolio`, and `backtesting` contain deterministic research logic. `brokers` adapts simulated and IG Demo execution. `database` persists results and audit evidence. `news`, `macro`, and `ai` are optional inputs that fail inactive. `notifications` provides bounded local alerts.

The code intentionally avoids distributed queues and microservices in V1. Backtest jobs run through a bounded local worker/service so the execution path remains inspectable and reproducible.

