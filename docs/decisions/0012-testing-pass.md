# 0012 - Phase 7 testing pass: failure injection, concurrency, and two real bugs found

## Decision
Close the specific coverage gaps identified by auditing Phases 3-6's incrementally-
written tests: failure paths that were built but never actually triggered, boundaries
never pushed on, and the one genuine race condition (idempotency under real concurrency)
worth proving rather than assuming. Document the webhook signature's lack of replay
protection as an accepted risk rather than fixing it, per explicit direction. Along the
way, this pass found and fixed two real bugs in how the global exception handler was
wired — not test artifacts, actual gaps in production behavior.

## Context
43 tests existed before this phase, each written alongside the feature it covered. That
approach is fine for proving new code does what it's supposed to when things go right;
it systematically under-covers *failure* paths, because triggering a failure on purpose
takes deliberate effort a feature-development test rarely spends. Phase 7's job (per the
original roadmap: "edge cases, failure injection, security scenarios") is to spend that
effort now, specifically on what was skipped.

## Options Considered

**Replay protection for the webhook signature**: document as an accepted risk (chosen,
per explicit direction) — versus adding a timestamp header the signature covers and
rejecting requests outside a short validity window. HTTPS in production already prevents
casual interception, and idempotency means a successful replay just looks like a
harmless duplicate lead, not a data-integrity problem. Chosen with a test
(`test_replayed_valid_request_is_accepted_not_rejected`) that actively proves the current
behavior, rather than leaving it as an implicit, undocumented gap — if replay protection
is ever added, that test should start failing, which is the intended signal to update it.

**How to prove concurrency safety**: `asyncio.gather` against the real app and real
database (chosen) — versus reasoning about the SQL alone. `INSERT ... ON CONFLICT DO
NOTHING` (ADR 0008) is safe *because* Postgres serializes concurrent writes to the same
constraint, but every existing duplicate test sent requests sequentially, which cannot
exercise the actual race window a check-then-insert would have failed on. Only genuine
concurrency (via `asyncio.gather`, interleaved against the app's real connection pool)
tests the actual claim.

## Two bugs found and fixed while writing these tests

**1. `@app.middleware("http")` (Starlette's `BaseHTTPMiddleware`) can let an exception
raised in a route escape past a registered exception handler**, due to how
`BaseHTTPMiddleware`'s `call_next` re-raises internally. Fixed by rewriting the
correlation ID middleware (`app/correlation.py`) as a plain ASGI middleware class
(`__call__(self, scope, receive, send)`) instead, which doesn't have this problem.

**2. `@app.exception_handler(Exception)`, used as a decorator after the app was already
constructed, never actually gets wired into Starlette's top-level catch-all
(`ServerErrorMiddleware`)** — confirmed by reading Starlette's own source
(`build_middleware_stack()`): a handler for the bare `Exception` class (or the `500`
status code) is only picked up if present in the `exception_handlers` dict *at app
construction time*. `HTTPException`-based handlers (everything else in this app —
401/422/429/503) go through a different layer (`ExceptionMiddleware`) and don't have this
limitation. Fixed by passing `exception_handlers={Exception: unhandled_exception_handler}`
directly to the `FastAPI(...)` constructor in `app/main.py`, rather than registering it
via the decorator afterward.

**What this means concretely**: before this fix, a genuinely unexpected exception in the
*real deployed app* — not just in a test — would never have reached our custom handler.
It would have fallen through to Starlette's own default error response, and
`sentry_sdk.capture_exception()` would never have been called. Phase 6's "we'll know
about real crashes" claim had a silent hole in it from the day it was built. This is
exactly the class of gap a dedicated testing pass exists to catch, and it did.

**A related, smaller finding**: proving fix #2 correctly required realizing that
`httpx.ASGITransport` defaults to `raise_app_exceptions=True` — it re-raises a server-side
exception into the calling test process *in addition to* the HTTP response the app
already sent, which is useful for catching accidental bugs during normal test
development but makes it impossible to test what a real deployed caller actually
receives. Added a second fixture, `client_like_real_deployment`
(`raise_app_exceptions=False`), used only by the specific test that needs to see the
real-world response rather than the debug-friendly exception.

## Decision Made

New test files, each covering one category:
- `tests/test_failure_injection.py` — DB failure at intake (`503`), health check DB
  failure (`503`), unhandled exception (`500` + Sentry capture, using
  `client_like_real_deployment`), the reconciliation sweep surviving an internal
  exception, and pipeline step independence at the code level (an adapter raising an
  outright exception, not just returning a classified failure).
- `tests/test_edge_cases.py` — field length boundaries (`name`/`phone`/`message`, both
  just-over-the-limit and exactly-at-the-limit), malformed JSON body, unicode/emoji
  content.
- `tests/test_concurrency.py` — ten genuinely concurrent identical requests, asserting
  exactly one non-duplicate response and exactly one database row.
- `tests/test_security_scenarios.py` — proof that 401/422/429 responses are structurally
  distinct from the generic 500 body (i.e., they're not accidentally being caught by the
  safety net), and the replay-risk-as-accepted-fact test described above.

Plus the two fixes: `app/correlation.py` (ASGI middleware class, not
`BaseHTTPMiddleware`), `app/main.py` (`exception_handlers=` at construction time).

## Why

The value of this phase wasn't primarily the new test count — it was that writing tests
specifically aimed at "what happens when this fails" surfaced two bugs that "what happens
when this succeeds" testing structurally cannot find. Both were real, both affected
production behavior (not just test correctness), and both are now fixed with a
regression test in place.

## Trade-offs

- **Replay protection remains genuinely absent**, by choice, not oversight — see the
  accepted-risk reasoning above. Revisit if this project ever handles a real client's
  production traffic over a channel where interception is a more realistic threat.
- **The two bugs found here were both about exception-handling wiring specifically** —
  this pass was not an exhaustive audit of every possible interaction between FastAPI/
  Starlette internals and this app's code; it's reasonable to assume more exist in areas
  not specifically probed by these tests, same as before this phase.
