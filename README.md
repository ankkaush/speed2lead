# Speed-to-Lead — Automated Lead Capture & Response System

A backend automation that receives a website lead submission, validates it, protects
against duplicate processing, persists it durably, pushes it to a CRM, notifies the
internal team, and sends the lead an acknowledgement — with retries, backoff, and
reconciliation so a lead is never silently lost even when a downstream service is down.

Built deliberately without AI-generated shortcuts, as a learning project covering the
full lifecycle of a real production automation: architecture, implementation, testing,
security, observability, and deployment — each phase documented as it happened in
[`docs/decisions/`](docs/decisions/).

**This is a public repository, released under the [MIT License](LICENSE) — free to use,
modify, and adapt to your own business.** See [Configuration](#4-configuration-your-own-credentials)
below to set it up with your own credentials, and
[Security considerations](#7-security-considerations) for what that means in practice.

**Live deployment**: [speed-to-lead-bscp.onrender.com](https://speed-to-lead-bscp.onrender.com)
(`/health` is public; `/leads` requires a valid signature — see
[§4](#4-configuration-your-own-credentials)). Deployed on Render per
[ADR 0014](docs/decisions/0014-deployment.md).

**Status**: Phase 9 (Production Review / Chaos Pass) complete. Rate limiting, Sentry
alerting, and correlation-ID tracing were all verified live against the deployed
instance; the real Phase 8 incident is written up as a formal postmortem
([ADR 0016](docs/decisions/0016-phase8-incident-postmortem.md)); and a second, unrelated
real finding — the Slack webhook URL leaking via a logging library's own automatic
request logging — was caught, fixed, and documented
([ADR 0017](docs/decisions/0017-slack-webhook-url-logging-exposure.md)). One item
remains open honestly rather than assumed complete: live end-to-end confirmation that the
rotated Slack webhook and the logging fix work together in production, blocked by
repeated clipboard-tooling friction rather than any known code issue — the fix passes all
61 automated tests locally.

## 1. What this automation does

```
Website form
   → API validates the submission
   → checks whether this exact submission was already processed (idempotency)
   → saves the lead to a database (this step succeeding is what "the lead is safe" means)
   → pushes the lead to a CRM
   → notifies the internal team (chat/Slack)
   → sends the lead an acknowledgement email
   → if any of the last three steps fails, it's retried automatically on a backoff
     schedule until it succeeds or is flagged for a human to look at
```

The CRM push, notification, and acknowledgement email are attempted independently — one
failing (a CRM outage, a bad API key) never blocks or hides the outcome of the others,
and nothing is ever silently dropped: every lead's status per step is stored, retried
automatically, and eventually either succeeds or becomes visible as needing attention
(via a dedicated error-tracking alert, not just a database row nobody looks at).

## 2. Architecture and major components

| Component | File(s) | Role |
|---|---|---|
| API / validation | `app/routes/leads.py`, `app/schemas.py` | Accepts `POST /leads`, validates input, enforces auth/rate limits |
| Idempotency | `app/idempotency.py` | Derives a dedup key so retries/duplicates don't create a second lead |
| Persistence | `app/leads_repo.py`, `db/migrations/` | The `leads` table — the single source of truth for every lead's status |
| Integration adapters | `app/adapters/{crm,notify,ack}.py` | One provider-specific implementation per role — see [§6](#6-replacing-or-customizing-an-integration) |
| Orchestration | `app/pipeline.py` | Runs the three adapters independently, classifies outcomes, hands off to persistence |
| Reliability | `app/reconciliation.py` | Background sweep retrying failed/stuck steps on exponential backoff |
| Security | `app/security.py`, `app/rate_limit.py` | Webhook signature verification, per-IP rate limiting |
| Observability | `app/correlation.py`, `app/logging_config.py`, `app/main.py` | Correlation IDs, structured JSON logs, real health check, Sentry |

Every non-obvious decision behind these — *why* Postgres over SQLite, *why* this
idempotency strategy, *why* no message queue — is written down in
[`docs/decisions/`](docs/decisions/) as a numbered ADR, in the order it was actually
decided. `docs/runbook.md` has the SQL an operator runs to check on the pipeline
directly, instead of a dashboard.

Guiding principle throughout: **simple enough to understand, robust enough to
demonstrate production engineering.** No microservices, Kubernetes, Redis, message
brokers, or unnecessary Docker/CI complexity unless a concrete requirement justifies it
— none has arisen yet at this project's scale.

## 3. Integrations currently included

| Role | Provider | Notes |
|---|---|---|
| CRM | [HubSpot](https://hubspot.com) | Free tier; upserts a contact by email (create or update, never a conflict) |
| Team notification | [Slack](https://slack.com) | A single incoming webhook — no OAuth app needed |
| Acknowledgement email | [Resend](https://resend.com) | Free tier's shared sending address; see [§5](#5-running-it-locally) for its recipient restriction |
| Database | [Supabase](https://supabase.com) (Postgres) | Free tier |
| Error tracking / alerting | [Sentry](https://sentry.io) | Free tier |
| Hosting (deployment target) | [Render](https://render.com) | Chosen for health-check-gated deploys matching this app's real `/health` check |

None of these are required to use this project's *code* — see [§6](#6-replacing-or-customizing-an-integration)
for swapping any of them.

## 4. Configuration: your own credentials

Copy the template and fill in your own values — **never** commit the result:

```bash
cp .env.example .env
```

| Variable | What it's for | Where to get it |
|---|---|---|
| `DATABASE_URL` | Postgres connection string | Your own Supabase project → Connect → **Session pooler** (not the direct-connection host — that requires IPv6, which many networks don't support) |
| `HUBSPOT_ACCESS_TOKEN` | CRM API auth | HubSpot → Settings → Integrations → Private Apps (scopes: `crm.objects.contacts.read`/`.write`) |
| `SLACK_WEBHOOK_URL` | Team notification | Slack → api.slack.com/apps → your app → Incoming Webhooks |
| `RESEND_API_KEY` | Acknowledgement email | Resend → API Keys |
| `SENTRY_DSN` | Error tracking | Sentry → new project (Python/FastAPI) → the DSN it shows you |
| `WEBHOOK_SIGNING_SECRET` | Authenticates callers of `POST /leads` | Generate your own: `python3 -c "import secrets; print(secrets.token_hex(32))"` — this one isn't issued by a provider, you invent it and share it with whatever system calls this API |

Apply the database schema (`db/migrations/*.sql`, in order) to your Postgres database
before running the app.

## 5. Running it locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
curl http://127.0.0.1:8000/health   # should return {"status": "ok", ...}
```

Run the tests (they run against the real database in your `.env`, deliberately — see
[ADR 0004](docs/decisions/0004-crm-integration.md) for why this project prefers real
dependencies over mocks where practical):

```bash
pytest
```

`POST /leads` requires a valid signature ([ADR 0010](docs/decisions/0010-security-hardening.md)):

```bash
BODY='{"name":"Test","email":"you@example.com","message":"hello"}'
SIG=$(python3 -c "import hashlib,hmac,os,sys; print(hmac.new(os.environ['WEBHOOK_SIGNING_SECRET'].encode(), sys.argv[1].encode(), hashlib.sha256).hexdigest())" "$BODY")
curl -X POST http://127.0.0.1:8000/leads \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Signature: $SIG" \
  -d "$BODY"
```

**Resend's free tier restriction**: without verifying your own sending domain, Resend
only delivers to the email address you signed up with — use that address as the `email`
field when testing locally, or the acknowledgement step will (harmlessly) fail with a
clear error.

## 6. Replacing or customizing an integration

The core pipeline (validation, idempotency, persistence, retry/backoff, reconciliation)
has **zero references** to HubSpot, Slack, or Resend by name — they exist only inside
`app/adapters/{crm,notify,ack}.py` and as env var names in `app/config.py`. To swap a
provider:

1. Write a new module with one async function matching the `StepAdapter` contract in
   [`app/adapters/base.py`](app/adapters/base.py):
   ```python
   async def attempt(lead, client: httpx.AsyncClient) -> StepResult:
       ...  # call your provider, return StepResult(outcome=..., external_id=..., error=...)
   ```
2. Point `app/pipeline.py`'s `_STEP_ADAPTERS` dict at your new module for that role.

That's the entire change — nothing else in the codebase needs to know or care which
provider is behind the call. See [ADR 0013](docs/decisions/0013-reusability-and-public-release.md)
for why this is a `Protocol` (a documented, structural contract) rather than a bigger
plugin/registry system: there's no second implementation to select between yet, so a
config-driven provider switcher would be solving a problem this project doesn't
currently have.

Swapping **hosting platforms** (away from Render) doesn't touch application code at all
— it's a deployment-config change (start command, env vars, health check path), not a
code change; see [ADR 0006](docs/decisions/0006-hosting.md).

## 7. Security considerations

- **Secrets never touch the repository.** `.gitignore` excludes `.env` and all
  `.env.*` variants except `.env.example`; `.env.example` contains variable names only,
  never real values. See [ADR 0002](docs/decisions/0002-public-repo-secrets-policy.md).
- **`POST /leads` requires a valid HMAC-SHA256 signature** over the raw request body,
  compared with a constant-time comparison (`hmac.compare_digest`) to avoid timing
  attacks. This assumes whatever calls this endpoint is a server that can keep the
  shared secret secret — a browser calling this API directly could never do that safely,
  since anything in client-side JavaScript is visible to anyone who opens dev tools. See
  [ADR 0010](docs/decisions/0010-security-hardening.md).
- **Known, accepted gap: no replay protection.** The signature has no timestamp or
  nonce, so a captured valid request could be resent. Documented and tested explicitly
  (not silently missing) in [ADR 0012](docs/decisions/0012-testing-pass.md) — idempotency
  means a replay is harmless (a duplicate, not a second lead), and this assumes HTTPS in
  production, which is what actually prevents casual interception in the first place.
- **Per-IP rate limiting**, in-process, no external service — a second layer, not the
  primary defense (that's the signature check).
- **PII (name/email/phone/message) never appears in application logs or in what's sent
  to Sentry** — only a lead's internal ID and status. This policy is applied consistently,
  not just at the logging layer: see [ADR 0011](docs/decisions/0011-observability.md) for
  where it also constrains what error text reaches third-party tooling.
- **No credentials of any kind are included in this repository** — see [§9](#9-no-credentials-are-included-in-this-repository).

## 8. Deployment considerations

Deployed as a single web service (no separate worker process — the reconciliation sweep
runs as a background task inside the same process, see
[ADR 0009](docs/decisions/0009-reliability-hardening.md)). For Render specifically:

- **Build command**: `pip install -r requirements.txt` (not `requirements-dev.txt` —
  test tooling has no reason to ship to production).
- **Start command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
- **Health check path**: `/health` — this endpoint genuinely verifies database
  connectivity (not a hardcoded "ok"), which is what makes Render's health-check-gated
  deploys meaningful rather than a rubber stamp. See [ADR 0011](docs/decisions/0011-observability.md).
- **Environment variables**: every value in `.env.example`, entered directly into your
  hosting platform's environment variable UI — never as a committed file. Use
  `APP_ENV=production`.
- **Database**: this project recommends a database dedicated to your deployed instance,
  separate from whatever you use for local development/testing — the automated test
  suite inserts and deletes rows against whatever `DATABASE_URL` it's given, which you
  don't want happening against real lead data.

## 9. No credentials are included in this repository

Every value in `.env.example` is an empty placeholder. This was verified before
publishing by auditing the entire git history (not just the current files) for the
specific formats this project's secrets take — see
[ADR 0013](docs/decisions/0013-reusability-and-public-release.md) for the exact checks
performed. Clone this repository and configure it with your own credentials per
[§4](#4-configuration-your-own-credentials); nothing usable is bundled with it.

## Architecture decision log

| # | Decision |
|---|---|
| [0001](docs/decisions/0001-language-framework.md) | Python + FastAPI |
| [0002](docs/decisions/0002-public-repo-secrets-policy.md) | Public-from-day-one secrets policy |
| [0003](docs/decisions/0003-database.md) | Postgres via Supabase |
| [0004](docs/decisions/0004-crm-integration.md) | HubSpot (private app token) |
| [0005](docs/decisions/0005-notification-and-email.md) | Slack incoming webhook / Resend |
| [0006](docs/decisions/0006-hosting.md) | Render |
| [0007](docs/decisions/0007-leads-data-model.md) | Single `leads` table, per-step status columns |
| [0008](docs/decisions/0008-idempotency-strategy.md) | Client key, server-derived fallback |
| [0009](docs/decisions/0009-reliability-hardening.md) | Classify + in-process backoff retry, no queue/broker |
| [0010](docs/decisions/0010-security-hardening.md) | HMAC signature (server-to-server) + in-process rate limit |
| [0011](docs/decisions/0011-observability.md) | Correlation IDs, real health check, Sentry, SQL runbook |
| [0012](docs/decisions/0012-testing-pass.md) | Failure injection, concurrency proof, accepted replay risk |
| [0013](docs/decisions/0013-reusability-and-public-release.md) | Adapter `Protocol`, MIT license, public-release audit |
| [0014](docs/decisions/0014-deployment.md) | Render blueprint, shared production database, separate prod secret |
| [0015](docs/decisions/0015-secret-hygiene-and-silent-failure-fix.md) | Secret whitespace validation, unexpected-exception handling fix |
| [0016](docs/decisions/0016-phase8-incident-postmortem.md) | Phase 8 incident postmortem |
| [0017](docs/decisions/0017-slack-webhook-url-logging-exposure.md) | Slack webhook URL logging exposure, fixed |

## Project roadmap

0. Discovery
1. Architecture & Key Decisions
2. Foundation
3. Core Lead Pipeline / Walking Skeleton
4. Reliability Hardening
5. Security Hardening
6. Observability
7. Testing Pass
8. Deployment
9. Production Review / Chaos Pass
10. Documentation *(current phase)*
11. Reusability Review
12. Case Study

Security, testing, logging, and documentation are treated as continuous practices
throughout every phase, not only during their dedicated phase.
