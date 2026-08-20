# Backtesting

The research engine is chronological and event-driven. It merges completed bars from every selected
market, advances an isolated simulation clock, ranks candidates that occur at the same timestamp,
challenges them, applies the authoritative RiskEngine, and schedules approved orders for that
instrument's next bar. One shared managed-capital ledger starts at £500; realised net P&L changes the
equity basis used by every later position size.

## Timing and look-ahead protection

Yahoo labels bars by interval start, so the importer moves each timestamp to a conservative interval
completion time before a bar can become visible. Daily and hourly data are never treated as
one-minute data. `GuardedBarSeries` exposes only observations at or before the simulation clock and
raises `FutureDataAccessError` if a strategy asks for the next candle. The test suite deliberately
attempts that access. Signals use completed bars, and orders execute at the next legitimate bar open.

For bar data, the next bar's OHLC is the finest available execution path. Entry occurs at its open;
stops and targets may then be touched within that bar. If both are touched and no lower-timeframe
path is available, the official `CONSERVATIVE` policy takes the adverse stop outcome. Gaps through a
stop fill at the worse opening price. Daily positions are normally held for at most two processed
bars and hourly positions for 25, allowing an approximately 24-hour research horizon.

## Costs, sessions and currency

Hardened research uses the versioned `instrument-research-costs-v1` schedule. Its `REALISTIC`
models preserve the original cost components as a floor and apply transparent market-specific
research uplifts. These figures are assumptions, not historical or current IG quotes. Every run
stores the effective per-market basis-point values and their provenance; the exact 1.5x robustness
scenario scales every component from those same models. Costs are recorded separately as spread,
slippage, financing, commission, guaranteed-stop premium, and conversion cost. Ordinary simulated
stops are not guaranteed and therefore pay no guaranteed-stop premium. Slippage, commission, and
currency conversion inputs are basis points per side; candidate forecasts and broker accounting
both apply them on entry and exit. Spread is already a full-spread input, and financing is per day.

Quote-currency amounts now use completed, point-in-time FX references rather than an implicit
fallback. USD converts through inverse GBP/USD, EUR through EUR/GBP, and JPY through inverse
USD/JPY multiplied by inverse GBP/USD; GBP is the identity. Approval/marking may use a completed
observation at the event timestamp. Under `modeled-bar-open-conversion-v1`, a next-bar execution is
anchored to `bar completion - configured interval` and resolves a conversion completed at or before
that modeled open. Intrabar and bar-close exits conservatively freeze the same modeled-open rate.
This prevents an asynchronously timestamped FX bar that completes during the execution bar from
leaking into its open fill or intrabar path. Missing, non-positive, or stale legs fail closed. The
former fixed rates are available only through an explicit legacy-comparison policy and are not the
service default.

Fill risk is recomputed from the modeled opening price and conversion. Because the simulator
processes bars at completion, it does not read potentially later completion-state equity backwards
into the open. Instead, `fill-risk-revalidation-v1-reservation-capped` uses the original causal
approval reservation and permits only an equal or smaller position size, planned risk, notional,
and margin; a breach rejects the fill. An irregular next-bar completion whose modeled open would
precede the original signal is likewise rejected before reaching the broker.

Historical eligibility uses `research-market-sessions-v1`: a versioned research proxy based on
the instrument's own completed bars, conservative intraday windows, and a maximum gap to the next
own-market bar. It is not asserted to reproduce historical exchange or broker hours. Orders that
cannot reach an eligible next bar inside the gap limit expire without being sent.

External operating costs are separate from trading costs. When configured, they are posted as a
terminal ledger deduction and consistently affect final equity, return, CAGR, drawdown, period
returns, milestones, lowest equity, and ruin status. The default credential-free run has £0 of paid
data, news, AI, or hosting cost.

## Genuine data and reproducibility

Import and run the predeclared studies:

```bash
make data-real
.venv/bin/python scripts/import_historical.py --preset intraday-core
make backtest-real
make research-protocol
.venv/bin/python scripts/run_backtest.py --preset official-intraday \
  --output data/exports/official-intraday.json
```

`official-daily` uses all nine declared daily markets from 2018-01-01 through the last complete bar
before 2026-08-19. It runs Quant Baseline, Quant Aggressive, Regime Ensemble, and Cash using the same
bars, £500 start, market-specific research costs, causal FX conversion, conservative fills, and
seed 8500. `official-intraday` uses the
longest reliably available recent hourly period, 2024-08-20 through the last complete bar before
2026-08-19. The result stores the strategy versions, configuration, manifest checksums, and a
SHA-256 run fingerprint. Identical input produces identical trades and fingerprint.

Frozen-protocol results additionally pin `strategy-source-manifest-v1`: normalized UTF-8 source
for every Python module under `app/strategies`, `app/opportunities`, `app/challenger`, `app/regimes`,
and `app/indicators` is hashed by logical module path. Checkout locations, `__pycache__`, `.pyc`,
database row IDs, and Git availability are not part of that identity. This content address catches
uncommitted logic changes that a repository revision alone would miss; any mismatch aborts the
protocol before a segment runs.

Downloaded CSVs, manifests, SQLite/PostgreSQL data, and JSON exports are ignored by Git. The
committed first-pass report contains the exact checksums and observed metrics without redistributing
provider bars. See [`docs/FIRST_BACKTEST_REPORT.md`](docs/FIRST_BACKTEST_REPORT.md).

## Metrics and robustness

Reports include returns, CAGR, drawdown depth/duration, trade distribution, expectancy, profit
factor, Sharpe, Sortino, Calmar, streaks, all trading costs, exposure/leverage, holding time,
instrument/strategy/regime breakdowns, monthly/annual returns, and £750/£1,000/£2,500/£5,000
milestones. Empty and losing results remain visible.

The frozen protocol runs five expanding annual folds with stability years followed by test years
from 2022 through 2026 YTD. Strategy versions and gates are fixed, every evaluation segment gets a
fresh £500 ledger and risk state, pre-segment bars are indicator/conversion warm-up only, test folds
are repeated exactly, and a 1.5x cost run is mandatory. Because the complete history had already
been inspected before this protocol was added, every result is labelled
`RETROSPECTIVE_PSEUDO_OOS`; it is not an untouched holdout. See
[`docs/RESEARCH_PROTOCOL.md`](docs/RESEARCH_PROTOCOL.md) for the frozen design and
[`docs/HARDENED_RESEARCH_REPORT.md`](docs/HARDENED_RESEARCH_REPORT.md) for the
completed fail-closed result.

The package also implements bounded parameter search with stability/overfit flags, seeded
bootstrap/permutation Monte Carlo, and stress scenarios for costs, delays, missing trades, smaller
winners, larger losses, gaps, and funding. These tools are research evidence, not permission to
promote or execute a strategy.

## Data limitations

Yahoo data is public research data, not a contracted or broker-grade feed. Gaps are counted and
never filled; exchange holidays remain visible; FX volume can be zero; continuous futures can have
roll effects; timestamps and price adjustments follow provider conventions. Daily-bar simulation
cannot establish intraday ordering beyond the conservative ambiguity policy. Backtests do not
predict Demo or Live execution quality.
