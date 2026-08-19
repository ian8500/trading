# IG Demo integration

The complete technical guide is in [docs/IG_INTEGRATION.md](docs/IG_INTEGRATION.md). V1 is strictly
Demo-only: the REST gateway is fixed to `https://demo-api.ig.com/gateway/deal`, returned streaming
hosts pass an explicit HTTPS Demo allowlist, both Live flags are typed false, and no Live broker can
be constructed.

> **Never paste IG credentials into GitHub, Codex prompts, issues, documentation or chat messages.**

Create a fresh key in the IG Demo platform under **My Account → Settings → API Keys**, then put the
values only in a local owner-readable `.env`:

```bash
cp .env.example .env
chmod 600 .env
```

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

The application works without these credentials. When configured, it can authenticate to Demo,
discover accounts without changing the preferred account, discover market/minimum-size/margin/stop
capabilities, read snapshots/history, construct current `PRICE`/`TRADE` Lightstreamer subscriptions,
submit only RiskEngine-approved orders, consume confirmations, reconcile positions/orders, and
operate a persistent stop/new-trade kill switch. A maintained Lightstreamer wire adapter must be
injected; REST polling is not silently presented as streaming.

The IG Demo balance is informational. Position sizing always uses the separate internal £500 ledger.
Every intent is persisted before its one allowed POST. Timeouts and ambiguous responses query
confirmation and positions but never blindly resubmit. Missing protection triggers a single bounded
remediation, then stop-and-close safety handling. Automation starts stopped on every process launch
and requires a fresh reconciliation plus authenticated manual start.

Dashboard controls are **Connect**, **Reconcile**, **Start autonomous Demo**, **Stop new Demo
trades**, and **Emergency close all**. They require a local administrator session, CSRF token, and
where appropriate an explicit confirmation phrase. Configure the administrator hash with
`.venv/bin/python scripts/hash_password.py`; no password or broker credential is stored in the
browser.

The adapter and its fake-server contract tests are exercised without secrets. Real authentication,
market discovery, Lightstreamer connectivity, and Demo order execution require the user's fresh
credentials and are never claimed unless actually run. See the detailed guide for current endpoint
versions, token refresh/reconnect policy, capability fields, order confirmation, reconciliation,
kill-switch semantics, limitations, and links to the official IG Labs references reviewed for this
implementation.
