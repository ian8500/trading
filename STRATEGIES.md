# Strategies

All first-pass strategies are deterministic, independently configurable, and operate without AI,
news, macro credentials, or broker access. They produce one common `OpportunityCandidate`; they do
not place orders. Every candidate receives inspectable expected-log-growth components, a
Devil's-Advocate challenge, and an independent RiskEngine decision.

## Trend and Breakout

The baseline combines fast/slow moving-average alignment, multi-period momentum, a completed-bar
high/low breakout, ATR volatility, spread, regime, and maximum-extension filters. Trend and breakout
must agree. Stops are ATR-scaled, targets use an explicit reward/risk multiple, and exits occur by
stop, target, holding expiry, circuit breaker, or end of data.

`Quant Baseline` predeclares 10/30 fast/slow periods, 10-period momentum, a 20-period breakout, a
14-period ATR, 1.5 ATR stop, and 2.0 reward/risk. It uses the Standard 2% hard risk cap.

`Quant Aggressive` is fixed before the comparison at 5/20 trend periods, 5-period momentum,
12-period breakout, 14-period ATR, 1.25 ATR stop, 1.75 reward/risk, and the Aggressive 4% hard cap.
The label describes its higher risk budget and faster rules; it is not an endorsement.

## Mean Reversion

The range strategy uses rolling mean distance, z-score, volatility normalisation, exhaustion,
spread, and regime checks. It will not trade blindly in a detected strong trend. It is independently
testable and is selected by the ensemble only when the deterministic regime permits it.

## Regime Ensemble

The ensemble detects trend and volatility from completed observations. It selects Trend/Breakout in
up/down trends, Mean Reversion in ranges, and no trade in unknown or disallowed high-volatility
states. The selected child evidence and ensemble weight are stored in the candidate explanation.

## Evidence and promotion

Uncalibrated candidates use a neutral prior with an explicit uncertainty penalty; historical support
is a causal count of completed observations beyond warm-up, not fabricated win-rate evidence.
Confidence never raises a hard risk limit. Strategy versions are immutable, champion/challenger
promotion fails closed, and the dashboard cannot promote a challenger without historical,
walk-forward, robustness, and forward IG Demo evidence.

The Cash baseline is always shown. It makes no trades, bears no trading costs, and prevents a
positive-looking strategy comparison from hiding that doing nothing was safer or better.
