# 0009 - Phase 4 reliability hardening: retries, backoff, reconciliation

## Decision
Classify every downstream outcome as success/transient/permanent; retry transient
failures on an exponential backoff (1 minute base, capped at 1 hour, 5 attempts max)
via a reconciliation sweep running in-process every 2 minutes; give up permanently on
permanent failures immediately. No message broker, queue, or separate worker process.

## Context
Phase 3 built the intake/persistence/idempotency pipeline but never wired the CRM/Slack/
email calls the `crm_status`/`notify_status`/`ack_status` columns exist for — those
columns were permanently stuck at `pending`. The central risk this phase closes: a lead
persisted successfully but never actually processed (transient failure, or the app
crashing mid-processing) with nothing watching to notice or retry it — a silent-drop
risk despite the row still existing in the database.

## Options Considered

**Failure handling model**: classify-then-route (chosen) — every adapter returns
success/transient/permanent, and one shared piece of code decides what happens next —
versus ad hoc per-integration try/except with no shared vocabulary, which risks
inconsistent handling (e.g. accidentally retrying a bad-credentials error forever, or
giving up on a 500 that would have succeeded on retry).

**Retry mechanism**: an in-process `asyncio` background task performing periodic SQL
sweeps against the existing `leads` table (chosen) — versus Redis/Celery/a message
broker/a separate worker process. At this project's volume (a single business's lead
form, not high-throughput event processing), a queue's core value — decoupling
producer/consumer rates, distributing work across many workers — doesn't apply. The
`leads` table with status + attempt-tracking columns already functions as a durable work
queue; a `WHERE` clause is the dequeue operation. Introducing a broker would add
deployment and operational surface (a new service to run, monitor, and secure) with no
concrete problem it solves yet.

**Where the first attempt happens**: synchronously within the intake request (chosen,
best-effort, once) — versus deferring all processing to the reconciliation sweep only.
Synchronous-first means the common case (everything succeeds) completes within one
request/response cycle with an accurate status in the response; deferring everything to
the sweep would mean every lead sits at `pending` for up to the sweep interval even when
nothing is actually wrong, and the caller never learns the outcome directly.

**Terminal state representation**: reuse the existing `failed` status for both "gave up
after exhausting retries" and "permanent failure, no point retrying" (chosen, per
explicit direction) — versus adding a distinct terminal status. Keeps the schema's
`step_status` enum unchanged from ADR 0007; the distinction between "exhausted transient
retries" and "classified permanent" is recoverable from `{step}_error` and
`{step}_attempts` if ever needed, without a fourth enum value.

## Decision Made

- **Classification** (`app/adapters/base.py`): `StepOutcome` = `SUCCESS` /
  `TRANSIENT_FAILURE` / `PERMANENT_FAILURE`. `classify_http_status()`: 2xx → success,
  429 or 5xx → transient, everything else → permanent. Network-level errors (timeout,
  connection failure) → transient. An adapter with no credentials configured
  (`HUBSPOT_ACCESS_TOKEN` etc. unset) → permanent, immediately, rather than silently
  doing nothing — an unconfigured integration should look like a problem, not like
  `pending`.
- **State transition** (`app/leads_repo.py: record_step_attempt`): one atomic SQL
  `UPDATE ... CASE` per step. Success → `success`. Permanent failure → `failed`
  immediately (retrying can't fix a bad token or a malformed request). Transient failure
  → `failed` once `attempts >= max_attempts` (5), otherwise stays `pending`.
- **Backoff** (`app/leads_repo.py: fetch_eligible_for_retry`): a row is eligible once
  `now() - {step}_last_attempted_at >= min(60 * 2^(attempts-1), 3600)` seconds — computed
  in SQL, not duplicated in Python, so there's one source of truth for the formula.
- **Reconciliation** (`app/reconciliation.py`): an `asyncio` task started in the FastAPI
  lifespan, sweeping every 120 seconds, independent of any request. Same process, same
  deployable as the API itself.
- **Timeouts**: `asyncpg` pool `command_timeout=10s`; shared `httpx.AsyncClient` with
  explicit 5s connect / 10s read timeouts (`app/http_client.py`), reused by every
  adapter.
- **DB failure at intake**: a narrow `try/except` around persistence
  (`asyncpg.PostgresConnectionError`, `asyncio.TimeoutError`, `OSError`) now returns
  `503` with a clear retry message and logs through the structured JSON logger, instead
  of an unhandled exception producing a bare, unstructured `500`.

## Why

This closes the actual reliability gap (a lead silently stuck mid-pipeline) with the
minimum mechanism that does the job: the database already durably holds the work items,
so the only missing piece was something that periodically asks it "what's not done yet"
and retries — not a new piece of infrastructure. Classifying failures once, centrally,
means every future integration (a second CRM, a different notification channel) gets
correct retry behavior for free rather than needing its own bespoke error handling.

## Trade-offs

- **A known gap, not resolved here**: HubSpot returns 409 when a contact's email already
  exists (HubSpot enforces email uniqueness). This is currently classified as a
  permanent failure with an explicit error message — not silently treated as success,
  but also not properly resolved (a proper fix is search-then-upsert against the
  existing contact). Flagged in `app/adapters/crm.py` and here as a follow-up.
- **Single-process reconciliation has a scaling ceiling**: if this were ever deployed as
  multiple app instances, two instances' sweeps could both pick up the same eligible row
  in the same window and attempt it twice — wasteful but not unsafe (the adapters aren't
  required to be literally single-flight; worst case is a duplicate outbound Slack
  message or CRM push attempt, not data corruption, since persistence itself remains
  protected by the original idempotency key). `SELECT ... FOR UPDATE SKIP LOCKED` would
  close this gap if it ever becomes a real deployment shape; not needed for a single
  Render instance.
- **`failed` is now overloaded** between "exhausted retries" and "permanent, no point
  trying." Chosen deliberately per direction to avoid a schema change; the distinction is
  still recoverable from `{step}_attempts` and `{step}_error` if ever needed.
- **Synchronous first attempt adds latency to the intake request** — up to three outbound
  HTTP calls (CRM, Slack, Resend) now happen before the response is sent, each bounded by
  the 5s/10s timeouts above. Acceptable at this project's scale; if it ever became a
  problem, the lever is deferring the first attempt to FastAPI `BackgroundTasks` (still
  no queue/broker needed) rather than blocking the response.
