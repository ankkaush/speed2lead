# Speed-to-Lead — Automated Lead Capture & Response System

A production-oriented learning project: an automation that receives a website lead
submission, validates it, protects against duplicate processing, persists it, pushes it
to a CRM, notifies the team, and acknowledges the lead — built deliberately without AI, to
learn the full lifecycle of designing, building, testing, securing, deploying, monitoring,
documenting, and maintaining a real business automation.

This is a **public portfolio repository**. See [`docs/decisions/0002-public-repo-secrets-policy.md`](docs/decisions/0002-public-repo-secrets-policy.md)
for the secrets policy this project follows: no real API keys, credentials, or personal
data are ever committed.

## Status

Phase 5 (Security Hardening) is in progress. `POST /leads` now requires a valid
HMAC-SHA256 signature (`X-Webhook-Signature` header, over the raw body, shared-secret
based — assumes a server-to-server caller, not a browser) and is rate-limited per client
IP; any unhandled error anywhere in the app now returns a generic response and is logged
structurally rather than leaking internals — see
[ADR 0010](docs/decisions/0010-security-hardening.md).

Phase 4 (Reliability Hardening) is functionally complete, including the real HubSpot/
Slack/Resend integrations it was designed to protect. `POST /leads` persists the lead,
then attempts CRM push, team notification, and acknowledgement email synchronously
(best-effort, once), classifying every outcome as success/transient/permanent — each
step independent, one failing never blocks the others. A background reconciliation sweep
(every 2 minutes, in-process, no external queue) retries transient failures on
exponential backoff (5 attempts max, 1 minute base, capped at 1 hour) until it gives up.
HubSpot upserts by email (create-or-update, no conflict on a repeat lead from the same
person); Resend uses the shared test sender (no domain verification yet — see
[ADR 0009](docs/decisions/0009-reliability-hardening.md) for the recipient restriction
that implies). See the phase roadmap below.

## Architecture (current decisions)

| Concern | Choice | Why |
|---|---|---|
| Language/framework | Python + FastAPI | [`0001`](docs/decisions/0001-language-framework.md) |
| Secrets/repo policy | Public-from-day-one | [`0002`](docs/decisions/0002-public-repo-secrets-policy.md) |
| Database | Postgres via Supabase | [`0003`](docs/decisions/0003-database.md) |
| CRM | HubSpot (private app token) | [`0004`](docs/decisions/0004-crm-integration.md) |
| Notification / email | Slack incoming webhook / Resend | [`0005`](docs/decisions/0005-notification-and-email.md) |
| Hosting | Render | [`0006`](docs/decisions/0006-hosting.md) |
| Leads data model | Single `leads` table, per-step status columns | [`0007`](docs/decisions/0007-leads-data-model.md) |
| Idempotency strategy | Client key, server-derived fallback | [`0008`](docs/decisions/0008-idempotency-strategy.md) |
| Reliability strategy | Classify + in-process backoff retry, no queue/broker | [`0009`](docs/decisions/0009-reliability-hardening.md) |
| Security model | HMAC signature (server-to-server) + in-process rate limit | [`0010`](docs/decisions/0010-security-hardening.md) |

Every significant architectural decision — what it is, why it's needed, what alternatives
were considered, and what trade-off is accepted — is recorded in
[`docs/decisions/`](docs/decisions/) as it's made.

Guiding principle: **simple enough to understand, robust enough to demonstrate production
engineering.** No microservices, Kubernetes, Redis, message brokers, or unnecessary Docker/
CI complexity unless a concrete requirement justifies them.

## Local setup

1. Clone the repo.
2. Copy the environment template and fill in your own local values:
   ```bash
   cp .env.example .env
   ```
   `.env` is gitignored and must never be committed — it holds real local secrets
   (your own Supabase connection string, HubSpot private app token, Slack webhook URL,
   Resend API key). `.env.example` only lists the variable names.

   `DATABASE_URL` must point at your own Supabase project's Postgres database — the
   **Session pooler** connection string (Project → Connect → Direct Connection tab →
   Session pooler), not the direct-connection host, since the direct host requires IPv6
   and many networks are IPv4-only. Apply the schema in
   [`db/migrations/0001_create_leads_table.sql`](db/migrations/0001_create_leads_table.sql)
   to that database before running the app.
3. Create a virtual environment and install dependencies:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements-dev.txt
   ```
4. Run the app:
   ```bash
   uvicorn app.main:app --reload
   ```
   Check it's up: `curl http://127.0.0.1:8000/health`
5. Run the tests (they run against the real database configured in `.env`, per this
   project's preference for real dependencies over mocks — see
   [`docs/decisions/0004-crm-integration.md`](docs/decisions/0004-crm-integration.md) for
   the same reasoning applied to the CRM):
   ```bash
   pytest
   ```
6. `POST /leads` requires a valid `X-Webhook-Signature` header as of Phase 5
   ([ADR 0010](docs/decisions/0010-security-hardening.md)) — an HMAC-SHA256 of the raw
   request body using `WEBHOOK_SIGNING_SECRET`. To call it manually:
   ```bash
   BODY='{"name":"Test","email":"you@example.com","message":"hello"}'
   SIG=$(python3 -c "import hashlib,hmac,os,sys; print(hmac.new(os.environ['WEBHOOK_SIGNING_SECRET'].encode(), sys.argv[1].encode(), hashlib.sha256).hexdigest())" "$BODY")
   curl -X POST http://127.0.0.1:8000/leads \
     -H "Content-Type: application/json" \
     -H "X-Webhook-Signature: $SIG" \
     -d "$BODY"
   ```

## Project roadmap

0. Discovery
1. Architecture & Key Decisions
2. Foundation *(current phase)*
3. Core Lead Pipeline / Walking Skeleton
4. Reliability Hardening
5. Security Hardening
6. Observability
7. Testing Pass
8. Deployment
9. Production Review / Chaos Pass
10. Documentation
11. Reusability Review
12. Case Study

Security, testing, logging, and documentation are treated as continuous practices
throughout every phase, not only during their dedicated phase.
