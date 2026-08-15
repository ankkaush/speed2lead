# 0010 - Phase 5 security hardening: signature auth, rate limiting, error handling

## Decision
Authenticate `POST /leads` with an HMAC-SHA256 signature over a shared secret (assumes
the caller is a server, not a browser); add a per-IP in-process rate limiter; add one
global exception handler covering every route. Defer database least-privilege role
scoping as a known, low-risk simplification at this project's current scale.

## Context
Before this phase, `/leads` had no authentication at all — anyone who found the URL
could submit arbitrary data, and only one specific failure path (a DB error at intake)
returned a safe, generic error response; every other unhandled exception fell through to
Starlette's default handling, which doesn't leak internals but also doesn't log through
this project's structured JSON logger.

## Options Considered

**Who calls `/leads`, and what that implies for authentication** — this was the load-
bearing question, not a detail. Two fundamentally different models:
- **Server-to-server** (chosen, per direction): the real website's own backend receives
  the form submission and forwards it to this API. A shared secret can genuinely stay
  secret, because it never has to reach a browser.
- **Browser calls the API directly**: a visitor's JavaScript calls `/leads` directly.
  No secret embedded in client-side code can be kept secret from that same visitor — the
  correct defenses in that model are rate limiting and CORS restricted to known origins,
  not authentication in the usual sense. Rejected as the assumed model per direction, but
  worth remembering if the project's deployment shape ever changes.

**Signature scheme**: HMAC-SHA256 over the raw request body (chosen) — the same pattern
Stripe, GitHub, and most real webhook providers use — versus a simpler static shared
"API key" header. HMAC has one meaningful advantage even in this simple case: the
signature is tied to the *exact content* of each request, so it can't be replayed against
a different payload even if somehow observed, and computing it doesn't require sending
the secret itself over the wire on every request the way a bearer-token-style API key
would.

**Rate limiting mechanism**: an in-process, per-IP sliding window (chosen) — versus a
Redis-backed limiter or an external service (Cloudflare, hosting-platform-level limits).
At a single-instance deployment with signature auth already the primary defense, an
in-memory limiter is proportionate; the value it adds is a second layer (protects against
a misbehaving integration retry-looping, or the secret ever leaking), not the sole line
of defense against a horde of anonymous attackers, which the signature check already
rules out.

**Error handling**: one global exception handler (chosen) — versus continuing to add
narrow `try/except` blocks per route as new failure modes are discovered (the approach
used for the Phase 4 DB-failure case). The global handler is a safety net underneath all
of those specific handlers, not a replacement for them — `HTTPException`-based responses
(401 from signature failure, 422 from validation, 429 from rate limiting, 503 from the
Phase 4 DB check) are untouched, since FastAPI/Starlette already handle those before
falling through to a generic `Exception` handler.

**Database role privilege**: deferred (chosen, per direction) — `DATABASE_URL` connects
as the `postgres` superuser via Supabase's pooler, more privilege than the app actually
needs (it only ever touches one table). Scoping this down to a dedicated role with
minimal grants is a legitimate improvement, but was explicitly deprioritized as
disproportionate effort for this project's current single-developer, low-stakes scale.

## Decision Made

- `app/security.py`: `verify_webhook_signature` — a FastAPI dependency that reads the raw
  request body, computes `HMAC-SHA256(WEBHOOK_SIGNING_SECRET, body)`, and compares it
  against the `X-Webhook-Signature` header using `hmac.compare_digest` (not `==` — a
  naive string comparison exits on the first mismatched byte, which a timing attack could
  exploit to guess the correct signature incrementally; `compare_digest` runs in constant
  time regardless of where the strings differ). Missing or mismatched → `401`, logged as
  a warning (no secret or body content in the log line).
- `app/rate_limit.py`: `check_rate_limit` — per-client-IP sliding window, default 20
  requests per 60 seconds (both configurable). Exceeding it → `429`.
- Both wired as `dependencies=` on the `/leads` route (not function parameters, since
  neither returns a value the handler uses) — rate limit first, since it's cheaper than
  computing an HMAC and should reject floods before spending any crypto effort on them.
- `app/main.py`: `@app.exception_handler(Exception)` — logs via the structured JSON
  logger and returns a generic `{"detail": "Internal server error"}` with no internal
  detail, for anything not already handled more specifically.
- `WEBHOOK_SIGNING_SECRET` added to `.env.example`/settings, required (fails fast at
  startup if missing, same pattern as `DATABASE_URL`). This secret is invented by us, not
  issued by an external provider, so it was generated directly
  (`secrets.token_hex(32)`) rather than requiring an account-setup dance.

## Why

The signature scheme only works because the submission model was clarified first — this
is the concrete example of why that architectural question mattered more than which
crypto primitive to use. Rate limiting and the global exception handler are both minimum-
footprint additions: no new infrastructure, no library that would hide the mechanism
(this project's own code implements the sliding window directly, which is also more
useful for learning the actual mechanism than importing one that hides it).

## Trade-offs

- **The rate limiter's IP-keyed dict never evicts stale entries** — acceptable given the
  expected caller count (one legitimate server-to-server integration), would need real
  eviction logic before this could safely front a high-traffic public-facing endpoint.
- **The database still connects with more privilege than it needs.** Explicitly deferred,
  not overlooked — revisit if this project's real-world stakes ever increase (e.g., a
  real client's production data flowing through it).
- **CORS was deliberately left unconfigured.** Correct for the server-to-server model —
  a browser calling this API directly would currently be blocked, which is the intended
  behavior under this architecture, not an oversight.
