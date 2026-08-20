# Data sources

## Yahoo Finance public chart data (V1 research source)

The credential-free provider downloads genuine OHLC bars from Yahoo Finance's public chart endpoint. It is **research-only and not broker-grade**. It is not a contracted data feed; availability, retention, adjustment policies, exchange timestamps and rate limits can change without notice. The application does not grant redistribution rights.

Provider symbols in the first daily run are `GBPUSD=X`, `EURUSD=X`, `JPY=X`, `EURGBP=X`, `^FTSE`, `^GSPC`, `^NDX`, `^GDAXI`, and `GC=F`. The hourly run also includes `BTC-USD`. Provider symbols are mapped to stable internal instrument IDs rather than leaking into strategy logic.

Every import writes an ignored CSV plus a JSON manifest containing provider, symbol, download time, requested/actual range, interval, provider timezone, row count, detected gaps, SHA-256 checksum, warnings, and usage note. Downloaded files under `data/historical/` are never committed. Before persistence, prices, volume, and quality scores are rounded half-up to their declared `NUMERIC` scales; this prevents database-specific tie rounding from changing a run fingerprint.

When a traded market settles in USD, EUR, or JPY, the backtest service loads the required GBP/USD,
EUR/GBP, and/or USD/JPY observations as causal conversion references. A reference series can be
loaded even when it is not in the requested trading universe; reference-only bars cannot produce
candidates, orders, trades, or ledger entries. Their manifests and completed-bar payloads still
enter the reproducibility fingerprint.

Validation rejects duplicate/non-monotonic/naive timestamps, non-positive prices, and material impossible OHLC relationships. A small number of Yahoo FX rows report high/low a few raw-feed ticks inside open or close. The importer may expand only sub-10-basis-point endpoint inconsistencies to include the supplied endpoint, records the count, and rejects larger inconsistencies as explicit gaps. It never fabricates or forward-fills missing bars.

Daily gaps include legitimate exchange holidays; warnings are retained because a generic downloader cannot infer every historical venue calendar. Futures data can contain roll/continuous-contract effects. Equity-index and futures timestamps follow provider/exchange conventions. Yahoo volume can be zero for FX.

Yahoo OHLC does not contain historical IG spreads, financing, commissions, minimum deal sizes, or
opening-hours history. The simulator therefore uses explicitly versioned research proxies for
those fields and stores `historical_ig_quotes: false` with each cost assumption. They must not be
described as observed broker terms.

## CSV

The local CSV provider requires timezone-aware `timestamp,open,high,low,close` columns, with optional `volume` and `complete`. The user remains responsible for provenance and usage rights.

## IG historical data

The IG adapter is available only after local Demo credentials are configured. IG capabilities and retention differ by market, resolution, account and API limit; discovery results are persisted and strategies must not assume support.

## Reproducing imports

```bash
make data-real
.venv/bin/python scripts/import_historical.py --preset intraday-core \
  --summary data/historical/intraday-import-summary.json
```

The official daily period is predeclared as 2018-01-01 through the last complete bar strictly before 2026-08-19. The hourly period is 2024-08-20 through the last complete bar strictly before 2026-08-19, reflecting the provider's reliable retention window observed for this run.
