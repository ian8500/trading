# Hardened research report

## Decision

**Do not promote any strategy to IG Demo.** Quant Baseline, Quant Aggressive,
and Regime Ensemble are all `NOT_ELIGIBLE`. Each failed multiple mandatory
after-cost gates under the frozen protocol, including aggregate return, profit
factor, median fold return, positive-fold count, stability return, and the
exact 1.5×-cost return. Quant Aggressive also breached the 15% worst-fold
drawdown limit.

Every result in this report is labelled `RETROSPECTIVE_PSEUDO_OOS`
(**retrospective pseudo-out-of-sample**). The complete 2018–2026 history had
already been inspected before protocol `1.2.0` was frozen. These results are
not a genuine out-of-sample test, not an untouched holdout, and not evidence
that authorizes Demo or live trading.

| Study identity | Value |
| --- | --- |
| Protocol | `nine-market-anchored-walk-forward` version `1.2.0` |
| Evaluation label | `RETROSPECTIVE_PSEUDO_OOS` |
| Markets | DAX, EURGBP, EURUSD, FTSE100, GBPUSD, GOLD, NASDAQ100, SP500, USDJPY |
| Data window | `2018-01-01T00:00:00Z <= timestamp < 2026-08-19T00:00:00Z` |
| Data | Yahoo Finance daily completed bars; public research data |
| Capital | Fresh `£500.00` ledger for each stability, test, and cost-stress segment |
| Strategies | Immutable `quant-baseline-v1`, `quant-aggressive-v1`, and `regime-ensemble-v1` |
| Result | Three of three `NOT_ELIGIBLE`; `promotion_allowed=false` |

## Methodology and disclosure

The evaluator used five expanding, anchored folds. The chronology called
"train" below performed no fitting, tuning, mutation, or winner selection. It
only recorded information that came before the fixed stability and test
segments. A causal 400-calendar-day prefix warmed fixed indicators and the FX
reference resolver, with trading suppressed until the segment began. Every
segment then started a new ledger, risk engine, breaker registry, broker state,
and strategy instance.

Intervals are half-open. Fold 5 includes completed observations through
2026-08-18 and ends at the originally declared exclusive boundary.

| Fold | Anchored chronology | Stability | Test and 1.5×-cost test |
| --- | --- | --- | --- |
| 1 | 2018-01-01–2021-01-01 | 2021-01-01–2022-01-01 | 2022-01-01–2023-01-01 |
| 2 | 2018-01-01–2022-01-01 | 2022-01-01–2023-01-01 | 2023-01-01–2024-01-01 |
| 3 | 2018-01-01–2023-01-01 | 2023-01-01–2024-01-01 | 2024-01-01–2025-01-01 |
| 4 | 2018-01-01–2024-01-01 | 2024-01-01–2025-01-01 | 2025-01-01–2026-01-01 |
| 5 | 2018-01-01–2025-01-01 | 2025-01-01–2026-01-01 | 2026-01-01–2026-08-19 |

The runs used `historical-simulator-v4-modeled-open-fx`, next-bar execution,
conservative same-bar ambiguity handling, a two-bar maximum holding period,
seed `8500`, causal quote-to-GBP references, the versioned
`instrument-research-costs-v1` schedule, and an exact component-by-component
1.5× rerun. All 45 stability/test/stress segments report
`causal_guard_passed=true`. Each of the 15 test segments was executed twice;
every repeated outcome fingerprint exactly matched its original.

## Eligibility gates

Protocol return and drawdown values in this section are decimal fractions, so
`-0.008136` means `-0.8136%`. Values below are the exact JSON values, without
rounding. A strategy must pass every row independently.

| Gate | Requirement | Quant Baseline | Quant Aggressive | Regime Ensemble |
| --- | --- | --- | --- | --- |
| Fold count | exactly 5 | `5` — PASS | `5` — PASS | `5` — PASS |
| Test reproducibility | all 5 exact | `5/5` — PASS | `5/5` — PASS | `5/5` — PASS |
| Aggregate after-cost return | `> 0` | `-0.008136` — **FAIL** | `-0.0537` — **FAIL** | `-0.0042` — **FAIL** |
| Aggregate profit factor | `>= 1.10` | `0.8582479615304202383441354798` — **FAIL** | `0.5930955051071439396235565120` — **FAIL** | `0.9265117581187010078387458007` — **FAIL** |
| Median fold return | `> 0` | `-0.01204` — **FAIL** | `-0.06272` — **FAIL** | `-0.01204` — **FAIL** |
| Positive test folds | `>= 3` | `2` — **FAIL** | `1` — **FAIL** | `2` — **FAIL** |
| Aggregate test trades | `>= 50` | `66` — PASS | `56` — PASS | `69` — PASS |
| Folds with at least 5 trades | `>= 4` | `5` — PASS | `4` — PASS | `5` — PASS |
| Worst fold maximum drawdown | `<= 0.15` | `0.05509009972202243259529965204` — PASS | `0.1544933796600619776504836135` — **FAIL** | `0.05580934237894368524386213868` — PASS |
| Ruin | none | `any_ruin=false` — PASS | `any_ruin=false` — PASS | `any_ruin=false` — PASS |
| Aggregate stability return | `> 0` | `-0.01094` — **FAIL** | `-0.0617` — **FAIL** | `-0.006696` — **FAIL** |
| Aggregate 1.5×-cost return | `> 0` | `-0.01328` — **FAIL** | `-0.019984` — **FAIL** | `-0.00626` — **FAIL** |
| Final verdict | every gate must pass | **`NOT_ELIGIBLE`** | **`NOT_ELIGIBLE`** | **`NOT_ELIGIBLE`** |

## Per-fold results

Returns and maximum drawdown remain decimal fractions. `Ann. T−S` is the
annualised test return minus the immediately preceding stability return. It is
the comparable degradation measure for fold 5, whose test is shorter than one
year. `1.5× return` is a complete rerun under scaled economics, not a
post-processing deduction.

| Strategy | Fold | Stability return | Test return | Test PF | Test trades | Test max DD | Ann. T−S | 1.5× return | Reproduced |
| --- | --- | --- | --- | --- | ---: | --- | --- | --- | --- |
| Quant Baseline | 1 | `-0.02606` | `0.02838` | `1.289296636085626911314984709` | 19 | `0.05509009972202243259529965204` | `0.054536531171299973` | `0.02274` | `true` |
| Quant Baseline | 2 | `0.02838` | `0.00284` | `1.051319118178532706902782797` | 20 | `0.02678223607323724191663420335` | `-0.0255623032026017774` | `-0.00528` | `true` |
| Quant Baseline | 3 | `0.00284` | `-0.01876` | `0.4868708971553610503282275711` | 7 | `0.03578` | `-0.0216615908953438076` | `-0.0213` | `true` |
| Quant Baseline | 4 | `-0.01876` | `-0.0411` | `0.4099913867355727820844099914` | 15 | `0.04651394422310756972111553785` | `-0.022378366021571394` | `-0.05488` | `true` |
| Quant Baseline | 5 | `-0.0411` | `-0.01204` | `0.5592972181551976573938506589` | 5 | `0.02756014016299854324973424151` | `0.022115617162751899` | `-0.00768` | `true` |
| Quant Aggressive | 1 | `0.01588` | `-0.09962` | `0.5840153666276933355603808251` | 15 | `0.1544933796600619776504836135` | `-0.11569569852809847` | `-0.04864` | `true` |
| Quant Aggressive | 2 | `-0.09962` | `-0.11334` | `0.3477960639889515479341696398` | 13 | `0.1134818429051351783714605663` | `-0.01462738424358689` | `0.01692` | `true` |
| Quant Aggressive | 3 | `-0.11334` | `-0.0487` | `0.2371553884711779448621553885` | 4 | `0.06288787753413322300372362433` | `0.065630607080178205` | `-0.05102` | `true` |
| Quant Aggressive | 4 | `-0.0487` | `-0.06272` | `0.5554925584691708008504606662` | 13 | `0.1029658864444531280528310734` | `-0.014043407798243865` | `-0.06224` | `true` |
| Quant Aggressive | 5 | `-0.06272` | `0.05588` | `2.341334613538166106577052328` | 11 | `0.04418068547695707672083674675` | `0.15303147625797753` | `0.04506` | `true` |
| Regime Ensemble | 1 | `-0.02452` | `0.04604` | `1.465614886731391585760517799` | 22 | `0.05580934237894368524386213868` | `0.07068629950522343` | `0.03972` | `true` |
| Regime Ensemble | 2 | `0.04604` | `0.00284` | `1.051319118178532706902782797` | 20 | `0.02678223607323724191663420335` | `-0.0432547293836689244` | `-0.00528` | `true` |
| Regime Ensemble | 3 | `0.00284` | `-0.0193` | `0.4797843665768194070080862534` | 8 | `0.03578` | `-0.0222025290019219886` | `-0.0213` | `true` |
| Regime Ensemble | 4 | `-0.0193` | `-0.03854` | `0.4258045292014302741358760429` | 14 | `0.04521943261846974097799705566` | `-0.019273077899235492` | `-0.03676` | `true` |
| Regime Ensemble | 5 | `-0.03854` | `-0.01204` | `0.5592972181551976573938506589` | 5 | `0.02756014016299854324973424151` | `0.019551267146994178` | `-0.00768` | `true` |

### Stability and consistency diagnostics

| Strategy | Test-fold return SD | Median raw T−S | Mean annualised T−S | Mean PF T−S | Non-degrading return folds |
| --- | --- | --- | --- | --- | ---: |
| Quant Baseline | `0.02310249648847500636710786909` | `-0.02160` | `0.0014099776429069786` | `-0.00278189275939610559951352364` | 2/5 |
| Quant Aggressive | `0.05963172444261527474949171819` | `-0.01372` | `0.014859118553645302` | `0.2368959231027339720068367794` | 2/5 |
| Regime Ensemble | `0.02843353794377337067301589684` | `-0.01924` | `0.0011014460734782406` | `-0.00574808325068089862875674994` | 2/5 |

None was broadly consistent across regimes or instruments. In pooled test-fold
P&L, all three lost money in their upward-trending classifications and made
money in downward-trending classifications: Baseline `-37.97/+28.53`,
Aggressive `-98.50/+25.71`, and Regime Ensemble `-45.76/+28.54` respectively.
Baseline and Regime Ensemble had positive aggregate instrument P&L only in
GBPUSD (`11.23` and `17.17`) and SP500 (`15.27` and `22.26`); every instrument
aggregate reported for Aggressive was negative. These are diagnostics, not
additional undeclared gates.

## Continuous full-history context

The separate `official-daily-v4` study used one continuously compounded £500
ledger over the full half-open window. It is context only. It is not directly
comparable with the protocol aggregate, which pools five independently reset
£500 test ledgers (`£2,500` total starting capital), and it is not promotion
evidence. Unlike protocol fractions, the official study reports return, CAGR,
and drawdown in percentage points.

| Strategy | Final equity | Total return | CAGR | Max DD | Trades | Profit factor | Costs | Reproducibility SHA-256 |
| --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | --- |
| Cash | £500.00 | 0.0% | 0.0% | 0.0% | 0 | `0.0` | £0.00 | `e45b054929753591b9bbc23c193e966fcbaba9ec0212f02b0b1ff7745c095c88` |
| Quant Baseline | £462.86 | -7.428% | -0.8906980424103428% | 9.383503984024745% | 112 | `0.845635910224439` | £40.81 | `d8e4ae5294961f4d869af5b0f63d640e15bbe8aafec15313d68fba195dbb1c2d` |
| Quant Aggressive | £454.57 | -9.086% | -1.0981084574979483% | 15.551385895816304% | 30 | `0.7347772782999591` | £16.29 | `e9a38914a1fa50448dd9b64d34d5bf679e8bc3f33bdb308e34f32127a23dce49` |
| Regime Ensemble | £481.20 | -3.76% | -0.4432683221217815% | 8.623079698448567% | 112 | `0.91974043715847` | £41.50 | `bd8c4bedd15d8f16878a8770c2d03a02e297000fd1cddfa96a492e76aece8ba0` |

Quant Aggressive's continuous path closed its final trade at
`2020-03-21T00:00:00Z` and recorded `0.0%` annual return for every year from
2021 through 2026. The artifact contains 198 later rejected candidates carrying
the `ROLLING_DRAWDOWN` circuit-breaker reason, from
`2023-08-11T23:00:00Z` through `2026-08-14T13:30:00Z`. Its later trading inside
walk-forward folds is not contradictory: those segments intentionally reset
the breaker and risk state, whereas the full-history study does not.

## Fingerprints and reproducibility

### Canonical identities

| Identity | SHA-256 |
| --- | --- |
| Protocol | `6b838d50b415e60ab7bc998b45f381cd2767bc8f7ecb41d6e7a848a977022ec3` |
| Source/data | `7ac0484620c95d73b2c4b1a867c00356f694f5e40e8d0ee3ed0b2112c12d7ef1` |
| Completed-bar payload | `9fea2995dd98bca98c6105f3149d013dd3eaf00d34a7066412ba2e26d1e563ff` |
| Strategy implementation | `f00f248c32b056a51cd3d710e9d1cde1dbfb17d0f186a55622afb2c7812e76b8` |
| Canonical report | `cf9545132ee289da313dd7fdefc64c57cd33f3807f9c4e9a9e919e90956feed8` |
| Shared economics | `9afe2db740d65f4d4d3f27f824794544026f5c635f472f54fdb9ddd98e876e60` |

| Strategy | Strategy fingerprint | Configuration fingerprint | Result fingerprint | Parameter state stable |
| --- | --- | --- | --- | --- |
| Quant Baseline | `b82a178e2c8192c4a63ae2d68e9430232fc5839d75b9503078465c64f8c3ea4f` | `b958ce4f3a21b5fed6ed92929345df0fb2bcf377745cebf3f0e02796d075151e` | `1160b49f4d0d7f4d4956498f40792812364ba3a210dece777905569b265c1cc7` | `true` |
| Quant Aggressive | `b85865078319e4019769da7b7bc6f239735d417150600d48eb72f79424efd3b1` | `c15881ac2e632654b8781da339b87eec9573623ef7632bbfccbaea46a921dc8f` | `a2b79e9c585eeaa6969829205880a87864e95431ce496688b9369690ed6bf1f6` | `true` |
| Regime Ensemble | `34e2f004853a46109fb7b19a23ad6cda3ead52869767b45fbc16a422b01695dc` | `01e911b5da50615bfea55215f7f4ec70d4ccfdd91ce782d8dab04500b94e9371` | `422209b40eb6f45a20578beff79231263291096b23c2f7d1bfa322cc18e66f45` | `true` |

`parameter_state_stable=true` means that every fresh per-market strategy
instance exactly matched its predeclared immutable fingerprint. It does not
mean parameters were fitted successfully; no fitting occurred.

The strategy implementation identity uses
`strategy-source-manifest-v1`: 16 Python modules under `app/challenger`,
`app/indicators`, `app/opportunities`, `app/regimes`, and `app/strategies`.
Each entry records its logical path, normalized UTF-8 byte count, and SHA-256.
Runtime paths and bytecode are excluded, and source content is authoritative;
a Git revision is not required.

### Cross-run and cross-database checks

- The two SQLite protocol runs have exactly the same `.report` object,
  canonical report fingerprint, per-strategy result fingerprints, fold
  fingerprints, and test outcome fingerprints. Only envelope `generatedAt`
  differs.
- The PostgreSQL run has the same canonical report and outcomes. After removing
  `generatedAt` and the nine deployment-local `manifest_ids`, all portable
  content in all three protocol artifacts is identical. Canonical sorted compact
  JSON for that comparison hashes to
  `6669ca58375fa67ec1ff110bb448b34efd67bb7ba0c8ab6bd5ce9e23e0ad2bf0`.
  This comparison hash is an audit aid, not an application report identity.
- Both full-history runs have identical substantive results and the four
  reproducibility hashes shown above. Their differences are limited to
  `generatedAt`, result UUID/lifecycle fields, and rejected-opportunity UUIDs.
- All nine full-history `dataChecksums` exactly match the protocol manifest
  checksums.

Raw artifact hashes differ because intentionally non-canonical, run-local
metadata differs. They are included to prevent byte identity from being
mistaken for canonical reproducibility.

| Ignored local artifact | Generated at (UTC) | Raw file SHA-256 |
| --- | --- | --- |
| `data/exports/research-protocol.json` | `2026-08-20T00:12:03.736855Z` | `e66a7dd53e4350abcd6bbf2368314545bd76863fca4da3676f4e283994060e50` |
| `data/exports/research-protocol-repro.json` | `2026-08-20T00:12:03.550736Z` | `e0818fff652ad494f56d08921e92ed52e4f2a5c4e5e51cf702f9a8a013dafb25` |
| `data/exports/research-protocol-postgres.json` | `2026-08-20T00:10:48.729334Z` | `3e0e1857ddb1190d564cec3ad543636157335f0073457091127f86916e220274` |
| `data/exports/official-daily-v4.json` | `2026-08-19T23:50:15.351655Z` | `f47bed5b3b66ad799c3979239e2b427d809eaa260ae82bc65050707205fbbec6` |
| `data/exports/official-daily-v4-repro.json` | `2026-08-19T23:50:37.014491Z` | `cd9d04f33b08b865c28f1f2572f58b7dac9abb9aa0263f5f72a6dabef8c6d824` |

## Hardened implementation represented by this evidence

- Versioned per-market research costs replaced uniform economics, and the
  robustness run scales each cost component by exactly 1.5.
- Completed, point-in-time FX references replaced implicit static quote-to-GBP
  conversion. Entry and intrabar exit conversion is pinned to the modeled bar
  open, with missing or stale references rejected fail-closed.
- Fill-time risk is revalidated from modeled-open prices and cannot exceed the
  originally approved risk, size, notional, or margin reservation.
- Versioned market-session proxies and own-market next-bar rules reject or
  expire ineligible executions.
- The frozen evaluator enforces causal warm-up, fresh segment state, exact
  immutable strategy fingerprints, complete source manifests, exact test-fold
  repetition, per-fold/aggregate metrics, and fail-closed verdicts.
- Canonical fingerprints exclude generation timestamps and deployment-local
  manifest IDs while retaining those IDs as provenance metadata.

## Limitations and proxy caveats

- This is `RETROSPECTIVE_PSEUDO_OOS`, not genuine OOS. All history was already
  seen before the protocol was declared.
- Yahoo Finance bars are public research data, not a contracted feed and not
  historical IG prices. Gaps are explicit and unfilled. Manifest missing-count
  values range from `191` to `517`, while each market still passed the frozen
  source coverage and boundary checks.
- `instrument-research-costs-v1`, `research-market-sessions-v1`, contract
  minimums, financing, slippage, spread, and next-bar eligibility are research
  proxies. They are not asserted to be historical or current IG facts.
- The artifacts charged spread, slippage, commission, and financing. They
  recorded `0.00` operational cost, guaranteed-stop premium, and currency
  conversion cost, so this study did not measure those three burdens.
- Daily OHLC bars cannot reveal intrabar event order. The simulator applies a
  conservative ambiguity rule, but this is still less informative than
  broker-grade tick or lower-timeframe execution data.
- Fold aggregates pool independently reset paths; the continuous full-history
  path compounds state and can trip persistent breakers. Their capital and
  activity are therefore not directly comparable.
- Fold `n` stability reuses the same calendar segment that appeared as fold
  `n-1` test. This is expected in the anchored design, not a second independent
  sample. Fold 5 is partial-year, so its annualised degradation measure is more
  comparable than its raw return delta.
- The 1.5×-cost scenario is path-dependent: altered costs can change sizing,
  fills, rejections, and later state. Quant Aggressive therefore had 61 stressed
  trades versus 56 baseline test trades and a less-negative stressed aggregate
  return. This is a stressed-economics rerun, not a monotonic P&L haircut.
- No broker-side Demo forward execution, latency, rejection, slippage, funding,
  or operational reliability evidence is included.

## Required next action

Do not promote any current strategy to Demo. Preserve these immutable losing
results. Redesign and version the strategies under a new predeclared protocol,
then collect genuinely new prospective data that was not available during the
redesign. Only a future candidate that clears its frozen after-cost gates on
that prospective evidence should proceed to a separate IG Demo forward
validation and explicit human review. Live execution remains out of scope.
