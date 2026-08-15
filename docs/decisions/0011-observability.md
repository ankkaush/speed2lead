# 0011 - Observability: correlation IDs, real health check, Sentry

## Decision
Thread a correlation ID through every log line for a request (accepting the caller's own
`X-Request-ID` if supplied); make `/health` actually verify database connectivity; wire
up Sentry (already anticipated in config since Phase 2, never used) for both real crashes
and a deliberate "a lead step just gave up permanently" alert. No metrics/dashboard
infrastructure — the database already answers those questions; document the SQL instead.

## Context
Structured JSON logging existed since Phase 2, but three real gaps remained: no way to
tell which log lines belonged to the same request, no proactive notification of anything
going wrong (everything lived only in local stdout), and `/health` returned "ok"
unconditionally, which quietly defeated ADR 0006's choice of Render specifically for its
health-check-gated deploys.

## Options Considered

**Correlation ID source**: accept the caller's own ID if supplied, generate one as
fallback (chosen, per direction) — versus always generating server-side. Reusing the
caller's ID (when the server-to-server caller already has one, per ADR 0010's submission
model) lets their logs and ours be cross-referenced directly during an incident; always
generating our own is simpler but loses that.

**Threading mechanism**: a `contextvar`, read automatically by the log formatter (chosen)
— versus passing a correlation ID explicitly through every function call. A `contextvar`
is exactly the tool Python provides for "value implicitly scoped to the current
request/task, invisible to code that doesn't need it" — every existing `logger.info(...)`
call gets a correlation ID for free, zero changes to those call sites.

**Error tracking**: Sentry (chosen, per direction) — versus building any kind of custom
alerting. Sentry already existed as an unused placeholder in config since Phase 2; wiring
it up is completing planned work, not adding a new dependency to the architecture.

**Metrics**: documented SQL queries (chosen) — versus a dashboard tool (Grafana,
Prometheus, etc.). The database already holds a complete operational history per lead
(status, attempts, timestamps, error text per step); a dashboard would be visualizing
data that's already fully queryable, at a cost (a new service to run, configure, and
secure) this project's scale doesn't justify yet.

## Decision Made

- `app/correlation.py`: a `ContextVar` set by a middleware at the start of every request
  (from `X-Request-ID` if present, else a generated UUID), read by `JsonFormatter`
  (`app/logging_config.py`) and included in every log line automatically. Echoed back as
  a response header on every response, not just errors, so a caller always has the ID to
  quote when reporting an issue.
- `GET /health` now runs `SELECT 1` against the DB pool before responding; returns `503`
  if unreachable, `200` if not.
- `sentry_sdk.init()` runs inside the FastAPI `lifespan` function, not at module import
  time — this is what lets the test suite force Sentry off via `monkeypatch` before it
  ever initializes (an import-time `init()` would already have fired using whatever was
  in `.env` at process start, before any test got a chance to override it).
- `sentry_sdk.capture_exception()` is called explicitly inside the global exception
  handler and the health-check failure path, not left to Sentry's automatic
  instrumentation — because our own handler already catches the exception and responds,
  it never propagates far enough up the stack for Sentry's auto-capture to notice it on
  its own.
- `app/leads_repo.py: record_step_attempt` calls `sentry_sdk.capture_message()`
  (level `warning`, not an exception) the moment a step's status transitions to `failed`
  — this only ever happens once per step per lead, since the reconciliation sweep only
  ever calls this on rows still `pending`. The payload deliberately excludes
  `result.error`: a provider's error text could in principle echo back submitted data,
  and this project's PII policy applies to third-party observability tools, not only to
  application logs.

## Why

Each piece closes a gap that was already identified as a gap in an earlier phase (Phase 4
explicitly deferred "alert on stuck leads" to here; Phase 2 added `SENTRY_DSN` as a stub
specifically anticipating this work) rather than introducing new scope. The correlation
ID and health check are both small, load-bearing pieces of infrastructure hygiene with no
new moving parts; Sentry is the one new external dependency, and it's one this project
already planned for.

## Trade-offs

- **The rate limiter and reconciliation sweep still aren't correlation-ID-aware** — they
  run outside any single request's lifecycle, so there's no meaningful "request" for a
  correlation ID to attach to during a background sweep tick. Their log lines remain
  identifiable by their own distinct event names (`reconciliation_sweep`,
  `rate_limit_exceeded`) instead.
- **Sentry's free tier has event volume limits.** Not a concern at this project's current
  scale, but worth knowing before assuming every single warning-level message will always
  land if traffic ever grew substantially.
- **No dashboard means "how's the pipeline doing right now" requires deliberately running
  a query**, not glancing at a screen. Acceptable given this project's current operator
  (one person, on demand) — would need revisiting if this ever supported a team that
  needed at-a-glance status.
