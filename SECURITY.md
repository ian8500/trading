# Security

## Secrets

Never paste IG credentials into GitHub, Codex prompts, issues, documentation or chat messages. Treat any previously disclosed password as compromised and replace it before use.

Create the local configuration with restrictive permissions:

```bash
cp .env.example .env
chmod 600 .env
```

`.env`, private-key/certificate formats, tokens, databases, logs, caches, exports and downloaded data are ignored. `.env.example` contains blank placeholders only. Credentials are loaded only by the backend. They are not returned by public configuration, held in browser storage, embedded in frontend builds, or written to the database.

Run `make secret-scan` before every push. It uses Gitleaks when installed and the maintained `detect-secrets` scanner from the development environment as a local fallback. Pre-commit runs Gitleaks, Ruff and detect-secrets; GitHub Actions scans full history with Gitleaks.

## Dashboard control plane

The dashboard binds to localhost by default. Read-only screens work without a password, but broker/automation/risk/promotion controls are locked until `DASHBOARD_ADMIN_PASSWORD_HASH` is configured. Generate an Argon2 hash without placing the password in shell history:

```bash
.venv/bin/python scripts/hash_password.py
```

Paste the resulting Argon2 hash into `.env` as a single-quoted value so Compose does not interpret its `$` characters, for example `DASHBOARD_ADMIN_PASSWORD_HASH='<generated hash>'`. Single-quote IG secret values too if they contain `$`; the quotes are configuration syntax and are not part of the value.

The backend issues an opaque, HttpOnly, SameSite=Strict process-local session and a separate CSRF token. A reverse proxy deployment must add TLS and set secure cookies; remote exposure is not a supported V1 default.

## Broker and execution safety

- V1 accepts only `IG_ENVIRONMENT=DEMO`.
- Both Live enable flags are typed false; startup fails if set true.
- Only fixed Demo API/streaming hosts may resolve.
- A RiskEngine approval record is mandatory for every order intent.
- Ambiguous responses are reconciled and never blindly resubmitted.
- Unknown positions, unconfirmed stops, stale data and failed reconciliation block new orders.
- The persistent kill switch defaults to stopped after restart.
- Sensitive headers, passwords, keys and account IDs are redacted before logging.

## Untrusted news and AI

Feeds are bounded and sanitised; only metadata and short summaries are stored. Article text is explicitly labelled untrusted data. The optional OpenAI Responses adapter sends no tools, uses a strict JSON schema, disables response storage, validates output again with Pydantic, and has no reference to broker credentials or order methods. AI output cannot alter risk, sizing, broker mode or strategy promotion.
