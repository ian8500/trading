# First genuine historical research report

> Historical V1 evidence: this report intentionally preserves the original static-conversion,
> uniform-cost run. It is not the hardened market-economics or frozen walk-forward result. See
> `RESEARCH_PROTOCOL.md` and the later hardened report for the current research contract.

Generated on 2026-08-19 from the predeclared, untuned study windows. This is research evidence, not investment advice or a claim of future performance. All tested trading variants lost money after modeled costs; cash was the best result.

## Reproduction contract

- Data source: Yahoo Finance public chart API, cached locally; research-only and not broker-grade.
- Requested daily window: `[2018-01-01T00:00:00Z, 2026-08-19T00:00:00Z)`.
- Actual merged daily observations: 2018-01-02 00:00 UTC through 2026-08-18 23:00 UTC.
- Resolution: genuine provider `1d` bars; no lower-resolution bars were fabricated.
- Universe: GBP/USD (`GBPUSD=X`), EUR/USD (`EURUSD=X`), USD/JPY (`JPY=X`), EUR/GBP (`EURGBP=X`), FTSE 100 (`^FTSE`), S&P 500 (`^GSPC`), NASDAQ 100 (`^NDX`), DAX (`^GDAXI`), and Gold futures (`GC=F`).
- Starting managed equity: £500.00 with compounding on after every realised net P&L.
- Shared configuration: REALISTIC costs, CONSERVATIVE intrabar ambiguity, next-bar execution, seed 8500, static quote-to-GBP research conversion, and no risk taper.
- Cost preset: 2 bp round-trip spread, 0.5 bp slippage per side, 0.25 bp commission per side, and 0.5 bp financing per holding day.
- Operating costs: £0.00; paid AI, news, data, and hosting were disabled.
- Look-ahead controls: explicit simulation clock, completed-bar visibility guard, next-bar entry, and malicious future-access regression tests.

The final production-path commands were:

```bash
make data-real
make backtest-real
```

The backtest command was run twice after the final simulator-behaviour change. Metrics, trades, curves, order counts, rejection counts, and fingerprints matched exactly. Imported decimals are rounded half-up to the declared database scales before persistence, so SQLite and PostgreSQL produce the same research inputs and fingerprints from the same manifests.

## Dataset manifests

The nine manifests contain 19,849 validated daily rows. The validator recorded 3,322 expected-grid absences and did not fill them. That count includes legitimate weekends, exchange holidays, and closed sessions because V1 does not have complete historical venue calendars; it must not be interpreted as 3,322 corrupt missing trading bars. Materially impossible rows were rejected and left as explicit gaps. Minor sub-10-bp Yahoo FX endpoint inconsistencies were expanded only to include the provider-supplied open/close and were counted in warnings.

The report-only manifest-set identifier is `fd42e02a33aadaa8d9e463dc1a7938065b01f2f75f3aed9651eda506c6b9a745` (SHA-256 over sorted instrument/checksum pairs). The authoritative per-download SHA-256 values are:

| Instrument | Rows | Grid absences | SHA-256 |
|---|---:|---:|---|
| GBP/USD | 2,246 | 191 | `915fdec5ea3e91c9b6a2e130196235af0e891f1061b7758881a3c87f714c5a87` |
| EUR/USD | 2,244 | 193 | `70684cf6af87bef363e53a20a9a37cfccfe3e35aba07050a88886cf94523ea05` |
| USD/JPY | 2,245 | 192 | `4fabb108be0376c358f96982b23bd3c42c4290d97ee0519508caa3e5d0eb6d59` |
| EUR/GBP | 2,245 | 192 | `31645731c3e6b12dabd6623ae09252dd13475f83e6f2282f9b7a9977bdc258b8` |
| FTSE 100 | 2,178 | 508 | `43b2ec18ef1e4944cf3dbb4a3c64876ef6f55d091e5940d668dcb3a0cf71245d` |
| S&P 500 | 2,167 | 517 | `e242bdfdf899166b5133bd006fab236a804201777c2db7ab79b7293cc228e6da` |
| NASDAQ 100 | 2,167 | 517 | `5e3860ee35299d49ffe53956bf0b279ec091a3c57523cf0eb22ac7ef96b0d5f4` |
| DAX | 2,189 | 495 | `b55668585362911b191fa07f9eeeeb977f419d780091873a970af201f516763b` |
| Gold futures | 2,168 | 517 | `2580ca84952d1eaea8a1ddd624cfbc19232bd421c1c50fcb6e9088599f450f47` |

## Daily strategy comparison

| Variant | Final equity | Return | Max drawdown | Trades | Win rate | Avg winner | Avg loser | Profit factor | Sharpe | Sortino | Trading costs | Fingerprint |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Cash baseline | £500.00 | 0.000% | 0.000% | 0 | 0.00% | £0.00 | £0.00 | n/a | n/a | n/a | £0.00 | `8b3ce92f38a2fef7092e4fbf3548653258f4a3fa040e281dd342537198c41199` |
| Quant Baseline | £437.27 | -12.546% | 15.012% | 227 | 47.14% | £3.75 | -£3.87 | 0.865 | -0.751 | -1.026 | £64.75 | `b31f91765ed879c6533d7da88da34f17f63e4a3dfaebc3d7914afe7d2e6b0062` |
| Quant Aggressive | £466.40 | -6.720% | 15.419% | 16 | 31.25% | £15.48 | -£10.09 | 0.697 | -0.567 | -0.792 | £6.66 | `ec249f0f9841b7b00e5ba868874e8e1f775e58b0f0c6d2ec78f67a9bd09b9e7d` |
| Regime Ensemble | £450.63 | -9.874% | 13.582% | 220 | 47.27% | £3.84 | -£3.87 | 0.890 | -0.561 | -0.777 | £62.83 | `e52835493a81f0c387bff86fe847d6392efd132de3b2d637feca6bba3696fb4c` |

Quant Baseline paid £30.57 spread, £15.33 slippage, £11.18 financing, and £7.67 commission. It never reached £750, £1,000, £2,500, or £5,000; lowest equity was £437.27 and ruin was not reached.

The aggressive variant's last trade closed on 2019-01-30. Its 15.42% rolling drawdown then crossed the configured hard limit, so the RiskEngine latched the rolling-drawdown breaker and rejected later candidates. The low trade count is therefore a risk-control outcome, not evidence of an eight-year low-turnover strategy. Daily and weekly loss breakers reset at their UTC/ISO-period boundaries; rolling and total drawdown breakers deliberately remain latched.

## Genuine hourly study

The separate untuned hourly study requested `[2024-08-20T00:00:00Z, 2026-08-19T00:00:00Z)` and used GBP/USD, EUR/USD, S&P 500, NASDAQ 100, Gold futures, and Bitcoin (`BTC-USD`). Its 60,392 validated `1h` rows span 2024-08-20 01:00 UTC through 2026-08-18 23:00 UTC. The validator counted 15,528 expected-grid absences, dominated by normal closed hours for exchange-traded indices; nothing was interpolated.

The Regime Ensemble finished at £486.25: -2.750% return, 15.668% maximum drawdown, 60 trades, 36.67% win rate, £13.23 average winner, -£8.02 average loser, 0.955 profit factor, -0.080 Sharpe, -0.138 Sortino, and £16.81 total trading costs. No capital milestone was reached and ruin was not reached. Fingerprint: `6fae9e8265eae45a816a93811b4e978d272609957149aa147daec904880edd69`.

Hourly manifest-set identifier: `bae18ee769b84bd2f6c08d8e53da2e23025a4598504e8576b22886f28096fbb2`.

| Instrument | Rows | Grid absences | SHA-256 |
|---|---:|---:|---|
| GBP/USD | 12,324 | 62 | `56ca10a394e2fa73bfe75f4acbee5bf4a977abdf7e8b1a9be84c11c96bd92fa8` |
| EUR/USD | 12,323 | 62 | `9c7d57e9d4e10ce2ec6c9b84f7021f1fcc2d5bbe9b5b0921c9099f1e9a115ea1` |
| S&P 500 | 3,485 | 7,358 | `e100fe450d2aa981c886c3f9c206904b66be38f9dda833fe1b67b30571f4668e` |
| NASDAQ 100 | 3,485 | 7,358 | `73a21e7209173f96536b77b3bd41dfcf029541aafdad21adbbef8f56923a3f06` |
| Gold futures | 11,470 | 535 | `b363c04a126ae2b3e035e600c7d23d5c14679d8aa9ea9af9b1f57cd159505aca` |
| Bitcoin | 17,305 | 153 | `e324fef228003501f180504a7faa03a0af8101a08a01ee1a05b2480e09315304` |

## Limitations

- Yahoo's public chart endpoint is neither contracted nor broker-grade, and availability, adjustments, retention, and timestamps may change.
- Daily bars cannot reveal intrabar path. Ambiguous stop/target touches take the adverse outcome; gaps through stops fill at the worse open.
- Static quote-to-GBP conversion factors replace historical FX conversion series in V1.
- The cost model is a transparent uniform research approximation, not historical IG per-market spreads, financing, or tiered commissions.
- Continuous futures can contain roll effects; index timestamps follow provider conventions; FX volume may be zero.
- No historical macro/news features or AI output affected these quantitative results.
- All strategy returns were negative. None is eligible for promotion or Live use; Live execution is absent in V1.
