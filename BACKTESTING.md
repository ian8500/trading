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

## Costs and currency

Official reports use `REALISTIC`: 2 basis points round-trip spread, 0.5 basis points slippage per
side, 0.25 basis points commission per side, and 0.5 basis points financing per day. Costs are
calculated from position notional and recorded separately as spread, slippage, financing,
commission, guaranteed-stop premium, and conversion cost. `OPTIMISTIC`, `STRESSED`, and explicit
zero-cost comparison presets also exist; a strategy is never approved from zero-cost evidence.

V1 converts quote-currency P&L into the GBP ledger with predeclared static research factors (GBP 1,
USD 0.78, EUR 0.86, JPY 0.0053). That makes cross-market accounting comparable but is an explicit
limitation: it does not model the historical conversion rate on each trade date. Broker-grade
research should replace it with timestamped FX conversion series.

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
.venv/bin/python scripts/run_backtest.py --preset official-intraday \
  --output data/exports/official-intraday.json
```

`official-daily` uses all nine declared daily markets from 2018-01-01 through the last complete bar
before 2026-08-19. It runs Quant Baseline, Quant Aggressive, Regime Ensemble, and Cash using the same
bars, £500 start, realistic costs, conservative fills, and seed 8500. `official-intraday` uses the
longest reliably available recent hourly period, 2024-08-20 through the last complete bar before
2026-08-19. The result stores the strategy versions, configuration, manifest checksums, and a
SHA-256 run fingerprint. Identical input produces identical trades and fingerprint.

Downloaded CSVs, manifests, SQLite/PostgreSQL data, and JSON exports are ignored by Git. The
committed first-pass report contains the exact checksums and observed metrics without redistributing
provider bars. See [`docs/FIRST_BACKTEST_REPORT.md`](docs/FIRST_BACKTEST_REPORT.md).

## Metrics and robustness

Reports include returns, CAGR, drawdown depth/duration, trade distribution, expectancy, profit
factor, Sharpe, Sortino, Calmar, streaks, all trading costs, exposure/leverage, holding time,
instrument/strategy/regime breakdowns, monthly/annual returns, and £750/£1,000/£2,500/£5,000
milestones. Empty and losing results remain visible.

The research package also implements rolling/expanding walk-forward splits, bounded parameter
search with stability/overfit flags, seeded bootstrap/permutation Monte Carlo, and stress scenarios
for costs, delays, missing trades, smaller winners, larger losses, gaps, and funding. These tools are
research evidence, not permission to promote or execute a strategy.

## Data limitations

Yahoo data is public research data, not a contracted or broker-grade feed. Gaps are counted and
never filled; exchange holidays remain visible; FX volume can be zero; continuous futures can have
roll effects; timestamps and price adjustments follow provider conventions. Daily-bar simulation
cannot establish intraday ordering beyond the conservative ambiguity policy. Backtests do not
predict Demo or Live execution quality.
