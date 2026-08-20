# Frozen retrospective research protocol

This protocol is labelled `RETROSPECTIVE_PSEUDO_OOS` everywhere: in prose,
**retrospective pseudo-out-of-sample**. The complete 2018–2026 history was
inspected before the protocol was frozen, so no split is an untouched holdout
and no result may be described as genuinely out of sample.

The protocol evaluates, without parameter changes or winner selection, the
immutable `quant-baseline-v1`, `quant-aggressive-v1`, and
`regime-ensemble-v1` strategy versions over the nine official daily markets.
Each strategy starts with £500 and uses its predeclared risk profile, realistic
after-cost economics, conservative same-bar ambiguity handling, next-bar
execution, a two-bar maximum holding period, and seed 8500.

## Frozen folds

Intervals are half-open (`start <= timestamp < end`). The final exclusive end
is 2026-08-19T00:00:00Z, matching the original predeclaration and including the
available completed observations through 2026-08-18.

| Fold | Anchored chronology | Stability segment | Test segment |
| --- | --- | --- | --- |
| 1 | 2018-01-01–2021-01-01 | 2021 | 2022 |
| 2 | 2018-01-01–2022-01-01 | 2022 | 2023 |
| 3 | 2018-01-01–2023-01-01 | 2023 | 2024 |
| 4 | 2018-01-01–2024-01-01 | 2024 | 2025 |
| 5 | 2018-01-01–2025-01-01 | 2025 | 2026-01-01–2026-08-19 exclusive |

The anchored “train” window performs no fitting, tuning, strategy mutation, or
selection. It records the predeclared chronology only. A fixed 400-calendar-day
prefix before each stability/test segment supplies causal observations to the
already-fixed indicators. The trading engine itself receives only segment bars,
so each segment creates a fresh ledger, risk engine, circuit-breaker registry,
broker state, and strategy instance. Warm-up bars cannot trade, enter the equity
curve, or alter breakers.

Conversion references are the GBPUSD, EURGBP, and USDJPY series already traded
inside every segment. Their strictly pre-segment warm-up prefixes seed the
causal conversion resolver and are merged with segment observations solely for
point-in-time conversion; reference bars never enter strategy, order, ledger,
equity, or breaker event streams. A missing or stale quote rejects the affected
decision rather than falling back to a future or static conversion.

Protocol version `1.2.0` pins conversion policy `quote-to-gbp-v1`, conversion
timing policy `modeled-bar-open-conversion-v1`, and simulator behavior
`historical-simulator-v4-modeled-open-fx`. Next-bar fills use the modeled open
instant (`completion - 1d` for this daily protocol); an FX observation that
completes after that instant cannot price the entry or the conservative
intrabar exit. The evaluator validates these identifiers against the engine and
includes them in protocol, configuration, and economics fingerprints. Fill
sizing is also pinned to `fill-risk-revalidation-v1-reservation-capped`, which
re-prices the approved reservation at the modeled open and never enlarges its
size, monetary risk, notional, or margin from later completion-state data.

Version `1.2.0` also pins the executable strategy stack through
`strategy-source-manifest-v1`. The manifest records the normalized UTF-8 source
SHA-256 and byte count for all Python modules under `app/strategies`,
`app/opportunities`, `app/challenger`, `app/regimes`, and `app/indicators`.
Logical module paths are portable; Git state, checkout paths, bytecode, and
platform line endings are excluded. Any source-content drift changes the
implementation digest and all implementation-bound research identities, or
fails closed if it no longer matches the frozen protocol.

Because no fitting occurs, the protocol does not publish misleading in-sample
training P&L. Instead it records each test return minus its immediately prior
stability return, the profit-factor delta where both values are finite, and
aggregate degradation dispersion. `parameter_state_stable=true` is emitted only
after every fresh per-market strategy instance exactly matches the predeclared
immutable strategy fingerprint. Test-fold instrument and regime P&L summaries
also report cross-fold presence, profitability counts, means, and dispersion.
Fold 5 is a partial 2026 interval while its 2025 stability segment is a full
year, so their raw total-return delta is not horizon-comparable to folds 1–4.
The report therefore also emits the annualised-return delta where defined. The
predeclared eligibility gates still use the specified raw aggregate and median
returns; degradation and dispersion are transparent diagnostics, not additional
undeclared pass/fail thresholds.

## Fail-closed gates

For each strategy independently, all conditions must hold:

- all five test folds reproduce exactly;
- aggregate test return after costs is greater than zero;
- pooled test profit factor is at least 1.10;
- median test-fold return is greater than zero;
- at least three of five test folds are positive;
- there are at least 50 aggregate test trades;
- at least four folds contain at least five trades;
- the worst fold maximum drawdown is no greater than 15%;
- no test fold reaches ruin;
- aggregate stability-segment return after costs is greater than zero; and
- aggregate test return remains positive under an exact 1.5× cost scenario.

The 1.5× scenario is constructed by scaling every component of each versioned
per-market `REALISTIC` research cost assumption by exactly `1.5`. The evaluator
checks spread, per-side slippage, per-side commission, financing, guaranteed-stop
proxy, and per-side conversion-fee fields independently before any segment runs.
Candidate forecasts count the conversion fee twice—entry plus exit—the same way
the broker books it against entry and exit notional. The evaluator does not
substitute the distinct built-in `STRESSED` preset.

Passing every retrospective gate still yields
`RESEARCH_GATES_PASSED_PROMOTION_BLOCKED`, never promotion approval. Untouched
prospective evidence, a separate IG Demo forward validation, and explicit human
review remain mandatory.

Any source mismatch, strategy drift, causal-boundary violation, strategy
exception, or missing segment data aborts report creation. Absence of a report
is a failed research run, never implicit eligibility.

## Reproducibility and output

The JSON report contains protocol, completed-bar data, strategy, configuration,
instrument/cost economics, segment, fold, strategy-result, and report SHA-256
fingerprints. Source bar content and manifest checksums are canonical. Database
manifest row IDs remain provenance metadata but are intentionally excluded from
canonical hashes so identical imports in SQLite and PostgreSQL compare equal.
The report also emits the strategy implementation schema, overall digest, and
each logical module's source digest and normalized byte count. The CLI’s
`generatedAt` value is outside every canonical hash.

Manifest-declared ranges, row counts, and missing-interval counts are retained
in the source fingerprint. Declared ranges/counts must match the completed rows,
each market must cover at least 85% of business days in the frozen window, and
the first/last observation must lie within ten days of the declared boundaries.

The command is intentionally non-persistent: it reads imported history and
writes an ignored JSON artifact, but creates no backtest, trade, opportunity, or
ledger database rows.

```bash
make research-protocol
```

Equivalent direct command:

```bash
.venv/bin/python scripts/run_research_protocol.py \
  --output data/exports/research-protocol.json
```

The final protocol `1.2.0` SQLite runs reproduced the canonical report and test
fold outcomes exactly, and PostgreSQL produced the same portable report after
excluding deployment-local manifest IDs. The provenance-complete evidence is
recorded in [`HARDENED_RESEARCH_REPORT.md`](HARDENED_RESEARCH_REPORT.md). Every
result remains `RETROSPECTIVE_PSEUDO_OOS`, all three strategies are
`NOT_ELIGIBLE`, and none authorizes Demo or live promotion.
