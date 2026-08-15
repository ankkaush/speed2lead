# 0015 - Secret hygiene validation, and closing a silent-failure gap

## Decision
Strip whitespace from every secret-bearing setting and reject values that still contain
embedded whitespace after stripping. Treat an adapter's unexpected (unclassified)
exception as a transient failure — recorded, retried, eventually surfaced — instead of
silently logged and dropped. Both found via a real incident during Phase 8 deployment,
not hypothesized in the abstract.

## Context
During the first live deployment, `RESEND_API_KEY` was pasted into Render's dashboard
with a trailing newline that absorbed the next line too, producing a value containing an
embedded `WEBHOOK_SIGNING_SECRET=...` assignment. `httpx` correctly refused to send that
as an HTTP header (`LocalProtocolError`, a real header-injection protection) — but its
exception message included the illegal value verbatim, which is how both the Resend key
and the production signing secret ended up in plaintext in Render's logs. Separately,
that exception wasn't one of the specific network-error types `app/adapters/ack.py`
catches, so it propagated to `app/pipeline.py`'s outer `except Exception`, which logged
it locally and returned — no Sentry alert, no attempt recorded. The affected lead's
`ack_status` stayed `pending` with `attempts=0` indefinitely; the reconciliation sweep
retried it every cycle and hit the identical unhandled exception every time, forever,
with zero visible progress toward either success or a surfaced failure.

## Options Considered

**Where to fix the secret-whitespace problem**: centrally, in `app/config.py` via a
`field_validator` on every secret-bearing field (chosen) — versus asking users to be more
careful pasting values into dashboards, versus fixing it ad hoc wherever a symptom next
appears. This is the third distinct incident of whitespace corrupting a secret value on
this project (a stray space after `DATABASE_URL=` in a local `.env` during Phase 3; two
separate line-concatenation incidents during `.env` editing; now this). Recurring
failures in the same shape are exactly what a validator belongs to, not another one-off
manual fix.

**Strip vs. reject**: strip leading/trailing whitespace automatically, but reject
(fail fast at startup) if whitespace remains *after* stripping (chosen) — versus
rejecting any whitespace outright, which would have required yet another manual,
error-prone re-paste in Render for a trailing newline that isn't even visible in most UI
text fields. Stripping handles the common, harmless case silently; rejecting embedded
whitespace still catches the actual dangerous case (two values concatenated) loudly, at
startup, instead of downstream as a confusing runtime error.

**Handling an adapter's unexpected exception**: classify it as `TRANSIENT_FAILURE`
(chosen) — versus leaving it unclassified/dropped (the prior, now-fixed behavior), versus
classifying it as `PERMANENT_FAILURE` outright. Transient is the safer default: some
unexpected errors genuinely are transient (a library hiccup, a one-off network condition),
and classifying as transient still means the attempt is *recorded* — it counts against
the attempt budget, so a truly persistent failure still reaches the existing
give-up-and-alert path in `leads_repo.record_step_attempt` after enough retries, rather
than looping unbounded and invisible.

**What to store in the error field**: `type(exc).__name__` only, never `str(exc)`
(chosen) — the exact lesson from this incident. An exception's message can itself contain
sensitive data (this is precisely how the secret leaked in the first place). The
exception class name is enough to diagnose from Sentry's full captured traceback without
risking a second copy of a leaked value landing in the `leads` table itself.

## Decision Made
- `app/config.py`: a `field_validator` (mode="before") applied to `database_url`,
  `hubspot_access_token`, `slack_webhook_url`, `resend_api_key`, `sentry_dsn`,
  `webhook_signing_secret` — strips the value, then raises if any whitespace remains.
- `app/pipeline.py: attempt_step`: an adapter's unexpected exception is now caught,
  reported to Sentry immediately (`sentry_sdk.capture_exception`), and passed to
  `record_step_attempt` as `StepResult(outcome=TRANSIENT_FAILURE, error=f"unexpected
  error in adapter: {type(exc).__name__}")` — recorded and retried like any other
  transient failure, rather than silently dropped.

## Why
Both fixes trace directly back to a real production incident, not a hypothetical one —
the validator would have caught the original misconfiguration at startup with a clear
error instead of a leaked secret; the pipeline fix would have made the stuck lead visible
in Sentry within a few retry cycles instead of silently stuck forever.

## Trade-offs
- **The validator adds a small amount of friction**: a secret value that happens to
  contain meaningful internal whitespace (none of this project's current secrets do)
  would need reconsidering. Acceptable given none of the six fields validated has a
  legitimate reason to contain whitespace.
- **Treating unexpected exceptions as transient means a permanent bug still costs
  `max_attempts` retries before it's flagged**, rather than failing fast on the first
  occurrence. Judged correct given the alternative (assuming permanent) would have
  falsely given up immediately on a genuinely transient error; the existing exponential
  backoff means those retries are spread out, not immediate.
