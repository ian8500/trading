# IG Demo integration

The V1 broker integration is intentionally **IG Demo only**. It can discover accounts and
markets, read snapshot and historical prices, construct Lightstreamer subscriptions, submit
risk-approved Demo orders, confirm them, inspect positions, reconcile durable state, and stop or
emergency-close Demo automation. There is no constructable IG Live broker.

This is leveraged-product automation for research and Demo testing, not financial advice. Demo
fills, liquidity, latency, slippage, margin behaviour, and market availability can differ materially
from Live.

> **Never paste IG credentials into GitHub, Codex prompts, issues, documentation or chat messages.**

## Local credentials

Create a fresh Demo API key using IG's Demo platform:

1. Sign in to IG's web platform with your own account.
2. Switch to the Demo environment or create a Demo account.
3. Open **My Account → Settings → API Keys**.
4. Generate a new Demo key and keep it only in the backend's local environment.

IG documents this flow in [Getting started](https://labs.ig.com/gettingstarted). Do not reuse a key
or password that has previously been disclosed.

Prepare the local file without printing its content:

```bash
cp .env.example .env
chmod 600 .env
```

Set these values manually in `.env`:

```dotenv
IG_ENVIRONMENT=DEMO
IG_USERNAME=
IG_PASSWORD=
IG_API_KEY=
IG_ACCOUNT_ID=

AUTONOMOUS_DEMO_ENABLED=false
LIVE_EXECUTION_ENABLED=false
LIVE_BROKER_IMPLEMENTATION_ENABLED=false
```

The application starts without these values. Credentials belong only in the backend process. They
must never be sent to the frontend, placed in browser storage, logged, or committed. The password,
API key, CST token, X-SECURITY-TOKEN, and configured account ID are memory-only in this package.

`IG_ACCOUNT_ID` is optional. If supplied, login selects that discovered Demo account with
`defaultAccount=false` and adopts the account's new XST. It does not change the user's preferred
account. A failed or unverified account switch aborts authentication.

## Environment boundary

The REST base URL is a code constant:

```text
https://demo-api.ig.com/gateway/deal
```

Configuration accepts only `DEMO`, HTTPS, the exact Demo hostname and gateway path, and disabled
Live flags. Redirects are disabled. Absolute resource URLs, traversal segments, custom ports,
credentials in URLs, query fragments in paths, the Production hostname, and any attempt to
construct `IGLiveBroker` fail closed.

IG says the Lightstreamer server must come from the login response and may change. V1 follows that
rule, then independently checks the returned HTTPS hostname against the reviewed Demo streaming
allowlist before giving it to a Lightstreamer adapter. A newly introduced IG Demo hostname will
therefore fail closed until the allowlist and tests are reviewed.

## Authentication and session refresh

The client uses `POST /session` version 2. IG returns CST and X-SECURITY-TOKEN headers, which are
required by the current streaming authentication scheme. The tokens are held only in memory.

IG's official pages currently disagree on v1/v2 token lifetime: the REST guide says six hours,
extended by use up to 72 hours, while the FAQ says a rolling 12-hour interval. The implementation
uses the shorter statement and deliberately creates a fresh v2 session after 5 hours 45 minutes. It
also refreshes and reconnects when a stream reports token/authentication failure, including the
weekend invalidation noted in the FAQ. No session token is written to SQLite.

Only read-only GET requests may repeat once after IG explicitly returns an invalid-token error.
POST, PUT, and DELETE operations never use automatic authentication retry because their execution
outcome may be ambiguous.

Logs contain method, relative resource path, HTTP status, and safe state transitions only. Login
bodies and broker headers are not logged. Exception messages retain IG's documented error code but
not response bodies or headers. A dedicated logging filter provides defense-in-depth redaction.

## Account and managed-capital separation

`GET /accounts` returns the broker Demo balances. Those values are informational only. They are not
an input to position sizing.

The strategy allocation remains the application's internal managed-capital ledger, initially £500.
The risk layer must size from current managed equity and persist a RiskEngine approval ID before it
constructs an `IGOrderIntent`. The IG order service requires that approval ID and an affirmative
approval flag. It never substitutes the often much larger broker Demo balance.

The order-intent and kill-switch SQLite file is restricted to owner read/write permissions when
opened. It contains no IG password, API key, CST, XST, or login response.

## Capability discovery

For each EPIC, `GET /markets/{epic}` version 3 is parsed into a provider-neutral capability record:

- instrument name, EPIC, instrument type, currency, market status, and opening hours;
- tradeability, market-order/force-open/attached-stop permission, snapshot availability, and
  account-specific streaming availability;
- minimum and (when actually advertised) maximum deal size;
- contract size, value of one pip, first margin band, and dealing-rule units;
- controlled-risk/guaranteed-stop availability and separate normal/guaranteed minimum stop and
  limit distances;
- expiry/rolling status and conservative overnight-funding classification.

Historical support is tri-state. It is `unknown` until explicitly probed through
`GET /prices/{epic}` version 3 because the market-detail response does not prove that historical
data exists for that EPIC. Probing consumes the historical allowance. A strategy requiring history
is eligible only when support is explicitly true.

Before submission, the order service rechecks the account-specific market detail, minimum size,
currency and expiry, directional stop/target levels, size/distance-rule units and minimums, and a
fresh non-delayed `TRADEABLE` snapshot. A missing capability, unrecognised rule, stale timestamp,
non-positive price, crossed quote, or unsupported guaranteed stop fails closed.

## Snapshot, history, and streaming

Snapshots use `/markets/{epic}` version 4, including the top price-ladder bid/ask and the epoch UTC
update timestamp. Version 3 remains in use for the richer capability fields, but its local
`updateTime` is not treated as a safe freshness timestamp. A timestamp is not fabricated when IG
omits it.

Historical prices use `/prices/{epic}` version 3 with the documented resolution, UTC range, maximum
point count, and pagination parameters. The response preserves bid and ask OHLC independently.

`IGStreamingService` supplies an adapter-neutral Lightstreamer contract:

- price item: `PRICE:{accountId}:{epic}`, `MERGE`, data adapter `Pricing`;
- price fields: top-tier bid/ask, quote IDs, UTC timestamp, dealing flag, and delay flag;
- trade item: `TRADE:{accountId}`, `DISTINCT`;
- trade fields: `CONFIRMS`, `OPU`, and `WOU`.

It enforces IG's default ceiling of 40 Lightstreamer subscription objects per connection and also
applies a conservative local limit of 40 EPICs in one price subscription. It uses one connection,
queues typed events, resubscribes after a bounded reconnect, and obtains fresh CST/XST credentials
on authentication disconnects. A queue overflow changes stream state to failed rather than silently
dropping data.
The legacy `MARKET:{epic}`/`L1` subscription is not used: IG's current reference says it reached
end-of-life on 1 May 2026 and was decommissioned on 8 May 2026 in favour of `PRICE`.

The repository provides the IG-specific abstraction and reconnect policy, not a bundled
Lightstreamer wire-protocol implementation. A production deployment must inject a maintained
adapter implementing `LightstreamerAdapter`; without one, `start_streaming` raises a configuration
error. REST polling is not silently substituted.

## Order safety and confirmation

Every immediate Demo order has a random internal intent ID that is also sent as IG's user-defined
`dealReference`. Before the first network submission, SQLite durably records:

- the intent ID and `PENDING_SUBMISSION` state;
- EPIC, direction, size, currency, and protection parameters;
- the RiskEngine approval ID;
- created and updated timestamps.

The persisted record contains no broker credential or session token. IG's `POST /positions/otc`
version 2 is called at most once for a given intent ID. Re-entering `submit` after a crash or timeout
can only query confirmation and position state; it cannot post the order again.

IG documents dealing as two phases:

1. acknowledgement returns a deal reference;
2. confirmation arrives on the trade stream (preferred) or from `GET /confirms/{dealReference}`.

Decoded `CONFIRMS` events are fed into a bounded in-memory confirmation cache and wake order
waiters. The REST confirmation service waits briefly for that stream when available and polls only
as the documented fallback. Accepted, rejected, malformed, delayed, and missing confirmations
become explicit durable states. If a POST transport error, 5xx response, missing acknowledgement,
mismatched reference, malformed confirmation, or unresolved delayed confirmation leaves the outcome
uncertain, the service:

1. marks the intent `AMBIGUOUS`;
2. queries `/confirms/{dealReference}`;
3. searches open positions for the same deal reference;
4. does **not** resubmit;
5. trips `AMBIGUOUS_ORDER_STATUS` if still unresolved.

## Protective stops

A protective stop is mandatory unless an explicitly different policy is encoded in the intent.
The service accepts a stop only when the deal confirmation or the open position confirms it.

If protection is missing, the service calculates an absolute level when necessary, sends one
`PUT /positions/otc/{dealId}` remediation request, confirms that request, then rereads the position.
A failed or ambiguous remediation is never blindly retried. The service first persists and trips
`PROTECTIVE_STOP_FAILURE`, then attempts to close the Demo position and confirm the close. New
trading remains suspended whether or not emergency closure succeeds.

## Reconciliation and autonomy controls

On startup or reconnect, reconciliation blocks new trading before it reads:

- all open positions (`GET /positions`, version 2);
- all working orders (`GET /working-orders`, version 2);
- every durable internal intent and confirmed deal ID.

It resolves pending/ambiguous intent references where possible, then reports matched, missing,
unknown, and unresolved records. V1 creates immediate orders only, so any broker working order is
unknown. Unknown broker positions, missing internal positions, unresolved intents, working orders,
or an API/database failure trip a persistent reconciliation breaker.

The durable safety service is OFF and blocks new trades on first use. On every normal process
restart it clears the running flag and requires a fresh reconciliation, even if the previous process
was running. It never resumes automatically by default.

After successful reconciliation and manual server-side intent, the controls are:

- `start`: enable autonomous IG Demo orders;
- `stop_new_trades`: persistently block new orders immediately;
- `emergency_close_all`: persist the stop first, close every discovered Demo position, confirm each
  close, and trip a critical breaker if any outcome remains unresolved;
- `acknowledge_circuit_breakers`: clear acknowledged reasons but remain stopped and require another
  reconciliation and manual start.

Closing and protection operations remain available while opening is blocked. This is required for
safe remediation.

## Official IG sources reviewed

These primary IG Labs pages were reviewed on **19 August 2026**:

- [REST trading API guide](https://labs.ig.com/rest-trading-api-guide.html): Demo/Production gateway,
  headers, versioning, v1/v2 CST/XST sessions, and v3 OAuth behaviour.
- [`/session` reference](https://labs.ig.com/reference/session.html): login versions, returned session
  fields, tokens, account switching, and error conditions.
- [`/session/encryptionKey` reference](https://labs.ig.com/reference/session-encryption-key.html):
  region-specific encrypted-password prerequisite documented as unsupported in V1.
- [`/accounts` reference](https://labs.ig.com/reference/accounts.html): version 1 account identity,
  currency, status, and balance fields.
- [REST API reference index](https://labs.ig.com/rest-trading-api-reference.html): supported endpoint
  and version matrix.
- [`/markets/{epic}` reference](https://labs.ig.com/reference/markets-epic.html): instrument,
  snapshot, dealing rule, margin, stop, and streaming capability fields.
- [`/prices/{epic}` reference](https://labs.ig.com/reference/prices-epic.html): version 3 resolutions,
  ranges, pagination, bid/ask OHLC, and allowance metadata.
- [`/positions/otc` reference](https://labs.ig.com/reference/positions-otc.html): version 2 create
  fields, user deal reference, force-open/protection constraints, and close request.
- [`/positions/otc/{dealId}` reference](https://labs.ig.com/reference/positions-otc-deal-id.html):
  version 2 protection updates and guaranteed/trailing stop constraints.
- [`/positions` reference](https://labs.ig.com/reference/positions.html): version 2 open position and
  market fields.
- [`/working-orders` reference](https://labs.ig.com/reference/working-orders.html): version 2 pending
  working-order fields.
- [`/confirms/{dealReference}` reference](https://labs.ig.com/reference/confirms-deal-reference.html):
  confirmation fields, rejection reasons, and REST-fallback guidance.
- [Trading basics](https://labs.ig.com/trading-basics.html): two-phase acknowledgement/confirmation,
  streaming preference, and the short REST-confirmation availability window.
- [API order types](https://labs.ig.com/api-order-types.html): market, limit fill-or-kill, working,
  attached stop, and limit semantics.
- [Streaming API guide](https://labs.ig.com/streaming-api-guide.html): server returned by `/session`,
  CST/XST streaming password, connection lifecycle, reconnect, and subscription constraints.
- [Streaming API reference](https://labs.ig.com/streaming-api-reference.html): current
  `PRICE:{account}:{epic}` and `TRADE:{account}` items, adapters, modes, and fields.
- [IG Labs FAQ](https://labs.ig.com/faq.html): exact Demo base URL, rate limits, historical ranges,
  streaming quota, and equity-price restriction.
- [Getting started](https://labs.ig.com/gettingstarted): Demo account and API-key creation.

## Published quotas and integration limitations

IG's FAQ currently publishes these defaults: 60 non-trading requests per app per minute, 30
non-trading requests per account per minute, 100 trading requests per account per minute, 10,000
historical points per week, and 40 concurrent streaming subscriptions. This package does not create
extra connections to evade those limits. Callers still need application-level rate scheduling and
backoff for sustained workloads.

Other limitations that must remain visible:

- No real IG call or Demo order is made by the automated tests; all transport and streaming
  behaviour is mocked. A user-controlled Demo smoke test is still required after configuration.
- IG says REST confirmations may be available for only about one minute. Durable reconciliation
  therefore also searches open positions by `dealReference`.
- Equity price streaming is not available according to IG's FAQ, and historical equity access can
  be restricted. Capability discovery must reject strategies that require unavailable data.
- `maximum_deal_size` stays unknown unless IG actually advertises a rule; price-ladder liquidity is
  not misrepresented as an absolute maximum.
- Overnight funding is marked true only for an explicit `DFB` expiry. Other products remain unknown
  and require a separate cost model; the code does not infer funding from a non-expiring `-` value.
- Market hours, minimum size, margin bands, stop distances, and stream permission are account- and
  instrument-specific and can change. They must be refreshed rather than cached indefinitely.
- Some regions require encrypted-password login. V1 uses session v2 over HTTPS with
  `encryptedPassword=false`; accounts that return IG's encryption-required error are unsupported
  until the official `/session/encryptionKey` RSA flow is implemented and tested.
- The Demo streaming allowlist currently contains the reviewed Demo host returned by IG. A future
  legitimate IG host change needs a deliberate code/test release, not a runtime override.
- Live readiness never activates Live. `LIVE_EXECUTION_ENABLED` and
  `LIVE_BROKER_IMPLEMENTATION_ENABLED` remain false regardless of Demo performance.
