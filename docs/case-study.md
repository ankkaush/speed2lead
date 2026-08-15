# Speed-to-Lead — Case Study

*Evidence-based project write-up. Every claim below is backed by a file, test, ADR, or
verified production check in the repository — cross-references are included so any
claim can be checked directly rather than taken on faith.*

## 1. Problem

Speed-to-Lead solves a common small-business failure mode: a lead arrives through a
website form, and nothing reliable happens next. Follow-up is manual, slow, or
forgotten; if a downstream system (CRM, notification channel) is briefly unavailable,
the lead can be lost entirely with no record it ever happened.

The system's job, from the moment a form is submitted:

1. An API receives the submission and validates it (name, email, message — anything
   malformed is rejected before anything else happens).
2. It checks whether this is a genuine duplicate of something already processed (an
   accidental double-submit, a network retry, a webhook redelivery) — using either a
   caller-supplied idempotency key, or, if none is supplied, a key derived from the
   email, the message content, and a short time window.
3. It persists the lead to a database. This is the actual safety net of the system —
   once persisted, the lead's data cannot be lost by anything that happens afterward.
4. It attempts, independently, to push the lead into a CRM (HubSpot), notify the
   internal team (Slack), and send the lead an acknowledgement email (Resend).
5. Whatever the outcome of step 4, a background process periodically checks for
   anything that didn't fully succeed and retries it on a backoff schedule, until it
   either succeeds or is flagged as needing a human's attention.

The core value isn't cleverness — it's that a lead's fate is always answerable:
submitted, and here's exactly what has and hasn't happened to it since.

## 2. Architecture

The backend is a single Python web service built with FastAPI. FastAPI was chosen
deliberately for its teaching value — its own documentation happens to be organized
almost exactly around the concepts this project needed to learn (validation, dependency
injection for concerns like authentication, testing, background tasks) — not because it
is objectively the "best" framework for the job.

Data lives in Postgres, hosted on Supabase (a hosting provider for Postgres, not a
different kind of database). The system's entire state — every lead, and exactly what
has happened to it — lives in one table. Rather than a generic event log, each lead has
three status columns, one per downstream step (CRM, notification, acknowledgement), each
independently `pending`, `success`, or `failed`. That makes "what's the state of this
lead" a single, direct query, not a reconstruction exercise.

Three outbound integrations exist today: HubSpot (CRM), Slack (team notification via a
single incoming webhook), and Resend (acknowledgement email). Each is a small,
self-contained module behind a shared interface (see §8).

The processing model is intentionally simple: when a lead comes in, the app tries all
three downstream steps once, synchronously, within the same request — so the common
case (everything works) completes and reports accurate status within a single HTTP
response. A background task, running inside the same process, wakes every two minutes
and retries anything still incomplete, on an exponential backoff schedule, until it
succeeds or exhausts its retry budget. There is no message queue or worker fleet — the
database itself, plus this periodic sweep, functions as the durable work queue, which is
proportionate to this project's actual scale.

## 3. Reliability

**Idempotency.** Two mechanisms decide whether an incoming submission is new or a
repeat: a key the caller can supply directly (if the calling system already has one), or
— if none is given — a key derived from the email address, the message text, and a
five-minute window. Either way, uniqueness is enforced by a database constraint
(`UNIQUE` + `INSERT ... ON CONFLICT DO NOTHING`), not by application code checking
"does this already exist" first. That distinction matters under real concurrency: a
check-then-insert has a race window where two simultaneous identical requests can both
pass the check before either has inserted, creating two leads instead of one. This was
specifically proven, not assumed: a test fires ten genuinely simultaneous identical
requests via `asyncio.gather` and confirms exactly one lead is created, with the other
nine correctly recognized as duplicates.

**Independence.** Each of the three downstream steps is attempted and recorded
independently. One failing never blocks or hides the outcome of the other two — proven
twice: manually, by genuinely breaking the Slack webhook URL and confirming HubSpot and
the acknowledgement email still succeeded; and automatically, with a test that makes one
adapter raise an outright exception and confirms the other two steps still run to
completion.

**A concrete failure-and-recovery example.** Suppose the acknowledgement-email step
times out because the email provider is briefly unreachable. Nothing about the lead is
lost — it was already persisted before any of the three downstream calls were even
attempted. The failed attempt is classified as transient, recorded (status stays
`pending`, attempt count becomes 1), and the lead sits safely in that state. The
background sweep checks every two minutes; it won't retry immediately (the backoff
schedule requires at least a minute to pass), but once eligible, it tries again
automatically, with no human involvement. If the provider has recovered, the retry
succeeds and the lead's acknowledgement status flips to `success` — without ever
creating a duplicate lead, losing the original data, or requiring anyone to notice and
intervene manually. If it keeps failing, the cycle repeats on a widening backoff (1
minute, 2, 4...) up to five attempts, after which the step is marked `failed` and an
alert fires (§5) so a person can look at it. This exact cycle — forced failure, confirmed
non-eligibility, confirmed eligibility once backoff elapsed, confirmed successful
automatic retry — was verified directly, not just designed.

## 4. Security

- **Authentication**: every request to the lead-intake endpoint must carry a valid
  HMAC-SHA256 signature over the raw request body, compared using a constant-time
  comparison to avoid timing-based guessing. This assumes the caller is a server capable
  of keeping a shared secret secret — it was deliberately not built to support a browser
  calling the API directly, since a secret embedded in client-side JavaScript can't
  actually stay secret.
- **Validation**: every field on an incoming submission is validated before anything
  else happens.
- **Rate limiting**: the endpoint is rate-limited per client IP, in-process — a second
  layer of defense, not the primary one (that's the signature check).
- **PII/logging protection**: name, email, phone, and message are deliberately excluded
  from both application logs and the data sent to the error-tracking tool — only a
  lead's internal ID and status ever appear there.
- **Secret management**: no credential of any kind is committed to the repository, in
  the current files or anywhere in its git history — verified by repeated, exact-format
  scans (not a generic keyword search) across every commit, not a one-time check.
- **Safe error responses**: errors returned to callers are deliberately generic (a plain
  "temporarily unavailable" or "internal server error"), with the actual detail logged
  internally instead of exposed.
- **Database access / RLS**: row-level security is enabled on the `leads` table with no
  policies defined, meaning access through Supabase's public API layer (which this
  application does not use) is denied by default. Worth being precise about what this
  does and doesn't protect: the application itself connects directly to Postgres using a
  role that bypasses row-level security entirely, so this specific safeguard defends a
  channel the app doesn't use — it does not restrict the application's own access.
  Scoping the app's own database role down to least privilege was identified as a real,
  legitimate improvement and explicitly deferred, not overlooked (§9, §11).
- **Replay protection is explicitly absent.** The signature scheme has no timestamp or
  nonce, meaning a captured valid request could technically be replayed. This is a
  documented, deliberate trade-off, not an oversight: idempotency means a replay just
  looks like a harmless duplicate submission, and the assumption is that HTTPS in
  production already prevents casual interception in the first place. A test exists
  specifically proving this current behavior, so if replay protection is ever added, that
  test will correctly start failing rather than silently continuing to pass.
- **A real credential exposure happened during deployment**, and is worth describing
  honestly. A copy-paste error while configuring the hosting platform corrupted one
  environment variable's value, in a way that caused a downstream library to raise an
  error whose message contained the corrupted, secret-bearing value — which then
  appeared in the platform's own log output. Two credentials were affected. Both were
  rotated immediately; the specific coding gap that allowed a malformed secret to reach
  that point was fixed (every secret-bearing setting is now validated and cleaned at
  startup); and a full audit confirmed nothing was ever exposed in the codebase or its
  version history — only in the runtime log output of one deployment, which was
  corrected. A second, unrelated issue was found shortly after through the same
  deployment scrutiny: one integration authenticates via a token embedded directly in a
  URL rather than a request header, and a logging library was, by default, recording
  that full URL on every call — an ongoing exposure through normal logging behavior, not
  a one-off mistake, until it was found and the logging configuration was changed to
  prevent it. Both incidents are written up in full as formal, dated records in the
  project's decision log, not left as informal notes.

## 5. Observability

- **Sentry** captures both genuine application crashes and a deliberate, separate alert
  the moment any lead's step permanently gives up — with the same PII-exclusion policy
  applied to what's sent there as to application logs.
- **Structured logs**: every log line is a JSON object, not free text, making it
  possible to search and filter by specific fields.
- **Correlation IDs**: every request carries one — supplied by the caller or generated —
  that automatically appears on every log line produced while handling that request,
  including from underlying libraries making outbound calls, so a single request's
  entire chain of events can be reconstructed from one identifier. This was verified
  directly against the live deployed logs, not just designed and assumed to work.
- **Health endpoint**: genuinely verifies the database is reachable rather than
  returning a hardcoded "OK" — the specific detail that makes the hosting platform's
  automatic deploy-health-gating meaningful rather than a formality.
- **Permanent-failure alerts**: confirmed live — three real Sentry events were captured
  matching three real downstream failures that occurred during deployment debugging, not
  a synthetic test.
- **Operator runbook**: rather than dashboard tooling, the questions an operator would
  actually ask ("how many leads today," "what's currently stuck," "what needs
  attention") are documented as direct SQL queries against the database, which already
  holds a complete record of every lead's history.

## 6. Testing

61 automated tests exist across nine files — but the number itself isn't the point.
What matters is which categories of failure they actually rule out, and the two real
bugs a dedicated testing pass specifically found.

What the tests actually prove, by category:

- **Failure injection** — a database outage during intake returns a clear, safe error
  rather than crashing; a genuinely unexpected, unclassified error anywhere in the
  request path is caught, safely reported, and never leaks internal detail to the
  caller; the background retry process survives its own internal errors and keeps
  running rather than dying silently.
- **Edge cases** — field-length boundaries, malformed request bodies, and non-Latin or
  emoji content are all handled correctly rather than assumed to be handled.
- **Security** — the specific response bodies for authentication failure, validation
  failure, and rate-limiting are proven structurally distinct from the generic
  crash-handler response (confirming they're not accidentally caught by the wrong
  handler), and a test documents the accepted replay-protection gap explicitly.
- **Concurrency** — the idempotency guarantee is proven under genuinely simultaneous
  requests, not just sequential ones.

**Two real bugs, found by writing these tests, not by inspection.** Both concerned how a
global safety-net error handler was wired into the web framework, and both would have
affected real production behavior, not just test coverage:

1. A certain style of custom request-handling code could let an error slip past the
   registered safety-net handler entirely, due to specific framework internals.
2. A safety-net handler meant to catch "anything unexpected" was registered in a way
   that — per the framework's own documented internals — never actually got wired into
   its top-level catch-all. A genuinely unexpected crash would never have reached the
   error-tracking tool at all, silently, until this was found and fixed.

Both were corrected, and a regression test now exists for each — the fix isn't a
one-time patch, it's a fact the test suite continues to enforce.

## 7. Production

The application is deployed on Render as a single web service, described by a
version-controlled deployment configuration file rather than manual dashboard
configuration alone — build command, start command, and health-check path are all
recorded in the repository.

Once deployed, behavior was verified against the live URL directly, not assumed from
local testing: authentication correctly rejecting and accepting requests, rate limiting
correctly triggering and later recovering, and all three downstream integrations
succeeding from the actual deployed instance.

**Development, testing, and production currently share one database.** This was a
deliberate but constrained decision, not an ideal one: the original plan was a fully
separate production database, reversed specifically because the hosting provider's free
tier caps the number of active databases per account, and creating a third would have
required pausing an unrelated existing project. Test data is isolated by a distinct,
clearly-marked email pattern and cleaned up after every automated test run — data-level
isolation, not the stronger guarantee a genuinely separate database would provide.

**A real incident occurred during initial deployment** (see §4) and is documented in
full as a formal, dated write-up rather than left as informal notes. It also incidentally
proved several of the system's own design claims under a real, unplanned fault: the
affected lead's data was never lost, and the other two downstream integrations were
completely unaffected by the one that failed — exactly the independence guarantee the
architecture was built around, demonstrated for real, not only in a test.

## 8. Modularity / Reusability

Every provider-specific integration — HubSpot, Slack, Resend — lives entirely inside its
own small, self-contained module. Each satisfies the same simple contract: given a lead,
return one of three outcomes (succeeded, failed but worth retrying, or failed
permanently). Nothing outside these three files, anywhere in the core pipeline,
persistence layer, or retry logic, references any of these providers by name — verified
directly by searching the entire codebase, twice, at different points in the project.
Replacing any one of them means writing one new module matching the same contract and
changing a single line that points to it; nothing else in the system needs to change or
even be aware a provider was swapped.

The hosting platform is not built into the application code at all — the only
environment-specific detail the app touches is which network port to listen on, a
convention shared by most hosting platforms, not specific to the one currently used.

The database story has two separate, honest halves. Using a different host for the same
Postgres database — a different provider, a self-hosted instance — requires no code
changes at all; nothing in the application code references the current hosting provider
specifically. Replacing Postgres itself with a different kind of database would be a
real, non-trivial change: the data layer uses several genuinely Postgres-specific
features (its native enumerated-type support, an atomic insert-or-ignore pattern, a
database-level trigger, and a database driver that only speaks this one engine), not a
generic, swappable data-access layer. This distinction was specifically checked, found to
be under-explained in the project's own documentation, and corrected — rather than
assumed to be fine.

## 9. Engineering decisions

The principle applied most consistently throughout: the simplest architecture actually
appropriate to the problem, not the most impressive-looking one. Concretely:

- Rate limiting is a small in-process mechanism, not a dedicated caching/rate-limiting
  service — appropriate because the authentication layer, not the rate limiter, is the
  actual primary defense, and traffic volume doesn't justify separate infrastructure.
- Retry and recovery work off the database itself plus a periodic in-process check, not
  a message queue or worker fleet — a queue's real value (decoupling many producers and
  consumers at meaningful volume) doesn't apply at this project's scale, and the
  database already durably holds every pending item.
- Provider integrations use a small shared interface, not a plugin framework with
  runtime provider discovery — there's currently exactly one implementation per role,
  and building a mechanism to select between options that don't exist yet is speculative
  complexity, not present value.
- Operational visibility is a documented set of direct SQL queries, not dashboard
  tooling — the database already holds everything needed to answer the questions that
  matter, and a dashboard would visualize data that's already fully accessible.
- Tightening the database connection to a minimally-privileged role was identified as a
  real, legitimate improvement and explicitly deferred rather than done — judged
  disproportionate effort for the project's current stakes, and recorded as a
  deliberate, revisitable decision rather than left as an unstated gap.

## 10. What I learned

- Idempotency under real, simultaneous concurrency is a meaningfully different claim
  than idempotency only ever tested with sequential retries — and the difference is
  exactly the kind of thing that looks fine until it doesn't.
- A web framework's error-handling internals can have real, non-obvious edge cases — a
  safety-net handler that looks correctly wired can still fail to actually catch
  anything, and the only way to find that out is to deliberately try to trigger it, not
  to read the code and assume it works.
- A secret doesn't only leak through a person's mistake — it can leak through a
  library's own error-reporting behavior, or through another library's default logging
  of something as innocuous-sounding as "the URL of an outbound request," when that URL
  happens to be how a particular provider's authentication works. Reasoning about where
  a credential can end up has to include this class of exposure, not just "did anyone
  type it somewhere they shouldn't have."
- Writing tests specifically aimed at failure ("what happens when this breaks") finds a
  different, often more valuable, class of bug than testing aimed at correct behavior —
  both real bugs in this project were found this way, not through code review.
- A reusability or portability claim needs to be re-verified against the actual current
  code before it's repeated, not just trusted from when it was first true — code changes
  underneath a claim like "this is swappable" without anyone updating the claim to
  match.

## 11. Limitations / honest caveats

This is a single-developer learning project that has been operated seriously, not a
system that has served real production traffic from real customers. Specific, honest
limitations:

- The acknowledgement-email integration is fully built and integration-tested, but
  cannot yet deliver to arbitrary real customer addresses — the email provider's free
  tier restricts delivery to the account owner's own address until a sending domain is
  verified, which hasn't been done.
- Development, testing, and production currently share one database, for a documented,
  constrained reason (a free-tier resource limit), not by design preference.
- The webhook signature scheme has no replay protection, by deliberate, documented
  choice, not oversight.
- The database connection uses more privilege than the application strictly needs;
  scoping it down was identified as a real improvement and explicitly deferred.
- The background retry mechanism assumes a single running instance; running multiple
  instances simultaneously would need an additional safeguard (row-level locking during
  the retry sweep) that hasn't been built, because it isn't needed yet.
- This project has not been tested under meaningful production load or traffic volume —
  everything described as "verified in production" refers to deliberate, individual test
  requests against the live deployment, not sustained real-world usage.
- Nothing here should be described as "enterprise-grade" — the architecture is
  deliberately proportionate to a small business's lead volume, not built to demonstrate
  scale it hasn't been asked to handle.

---

## Portfolio version (concise)

**Speed-to-Lead — Automated Lead Capture & Response System**

A backend automation (Python/FastAPI, PostgreSQL) that takes a website lead from form
submission through CRM push, team notification, and customer acknowledgement — with
idempotent deduplication, independent per-step retries with exponential backoff, and
automatic recovery, so a lead is never lost even when a downstream provider is
temporarily unavailable.

Built end-to-end as a solo project covering the full lifecycle of a real production
system: architecture and data-model design, HMAC-authenticated API security, structured
logging with request-level tracing, error tracking and alerting, a real deployment with
live verification, and a deliberate "break it on purpose" review pass — which found and
fixed two genuine bugs in how errors were being caught, plus a real credential-exposure
incident during deployment that was diagnosed, fixed at the root cause, and documented
rather than hidden.

Every HubSpot, Slack, and Resend integration sits behind a small shared interface, so
any of the three can be replaced with a different provider by writing one new module —
nothing in the core pipeline needs to change. 61 automated tests, 18 written
architecture-decision records, and a public repository with zero credentials ever
committed, verified by a repeated, exact audit of the full git history.

**Stack**: Python, FastAPI, PostgreSQL (Supabase), HubSpot API, Slack, Resend, Sentry,
Render.
