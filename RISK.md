# Risk controls

The RiskEngine is the authoritative execution boundary for historical and IG Demo orders. A
strategy, AI response, dashboard action, or broker adapter cannot bypass it: brokers accept only an
`ApprovedOrder` capability containing an affirmative deterministic decision ID.

## Managed capital and sizing

The internal ledger begins at £500 and is separate from the often much larger IG Demo balance.
Position risk is calculated from current realised managed equity, stop distance, point/contract
value, quote-to-GBP conversion, expected execution costs, gap allowance, size step, and minimum deal
size. Quantities are rounded down. If the minimum size exceeds permitted loss or available margin,
the trade is rejected rather than enlarged.

Profile risk per trade is Conservative 1%, Standard 2%, Aggressive 4%, or Experimental 6%. These are
hard maxima, not targets. Aggregate open risk, per-market exposure, effective leverage, margin,
concurrent positions, and direction-aware correlated risk are checked again for each ranked
candidate. The official daily baseline/ensemble use Standard; the explicitly labelled aggressive
variant uses Aggressive.

Optional tapering caps risk as equity grows. The research schedule is 4% below £1,000, 3% from
£1,000, 2% from £2,500, and 1% from £4,000, always limited by the stricter profile or strategy-health
cap. Taper bands are included in the reproducibility fingerprint and effective fractions appear in
the audit trail.

## Portfolio and margin

All markets share one ledger. Candidates at a common timestamp are ranked by the same score and
evaluated in rank order. Approved orders reserve risk, notional, margin, correlation cluster, and
exposure tags while waiting for their own next bar, preventing simultaneous candidates from
bypassing portfolio limits.

Default hard limits include three concurrent positions, 6% Standard open risk, 3x individual market
exposure/effective leverage, 50% margin usage, and 4% same-direction correlated risk. Instrument and
account capability checks can be stricter. Static research currency conversions are disclosed in
`BACKTESTING.md`; IG Demo uses discovered market metadata and account-specific rules.

## Circuit breakers

New orders fail closed on stale/impossible prices, abnormal spread, clock anomalies, strategy
exceptions or attempted look-ahead, daily/weekly loss, rolling/total drawdown, ambiguous broker
outcomes, missing protective stops, reconciliation discrepancies, stream/database failure, or the
kill switch. Unknown positions and working orders block autonomy. Closing and stop remediation stay
available while opening is blocked.

Stops are mandatory; they cannot be widened merely to avoid a loss. Martingale, grid averaging,
unbounded leverage, revenge trading, silent broker retry, duplicate ambiguous submissions, and
using the broker Demo balance as the sizing base are prohibited.

## Risk profiles are not guarantees

Historical bars cannot model every gap, rejection, liquidity shock, currency move, margin change, or
broker outage. A 2% planned stop loss can lose more than 2%. Demo fills do not prove Live behaviour,
and V1 contains no constructable Live broker. The readiness screen is informational and always
reports Live execution disabled.
