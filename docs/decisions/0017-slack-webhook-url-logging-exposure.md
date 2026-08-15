# 0017 - Slack webhook URL exposure via httpx's automatic request logging

## Decision
Suppress `httpx`/`httpcore`'s automatic per-request `INFO`-level logging at the source
(raise both loggers to `WARNING`). Rotate the Slack incoming webhook URL.

## Context
Found during Phase 9's live correlation-ID verification, not through a deliberate chaos
test: a screenshot of Render's logs, requested purely to confirm correlation IDs tie a
request's log lines together, incidentally showed the **full Slack webhook URL** in a log
line reading `"HTTP Request: POST https://hooks.slack.com/services/... \"200 OK\""`.

This is structurally different from the Phase 8 incident (ADR 0016), which was a one-time
human copy-paste error. This was a continuous, systemic gap: `httpx` logs the full URL of
every request it makes at `INFO` level, and this project's logging configuration
(`app/logging_config.py`) captures everything at the root logger, so that line has been
flowing into Render's persisted logs on **every single Slack notification sent**, since
Phase 6 — not a one-off mistake, an ongoing leak with every successful call.

The reason this specifically affects Slack and not HubSpot or Resend: Slack's incoming
webhook authentication model embeds the secret directly in the URL path itself (per
ADR 0005 — chosen specifically for its simplicity, "a single secret URL, no OAuth").
HubSpot and Resend both authenticate via an `Authorization` header, which `httpx`'s
request-logging line never includes — only the URL. The same webhook-in-URL design that
made Slack the simplest integration to build is exactly what made this logging gap
consequential specifically for Slack and not the other two.

## Options Considered

**Where to fix it**: suppress `httpx`/`httpcore`'s own logging at the source (chosen) —
versus redacting Slack URLs specifically wherever they're used, versus leaving `httpx`
logging on but filtering messages after the fact. Suppressing at the source is correct
because the actual problem is general, not Slack-specific: *any* future provider whose
auth model embeds a token in a URL (not just Slack) would have leaked the same way, and
this app never deliberately asked for `httpx`'s internal per-request logging in the first
place — everything meaningful it captures is already covered by this project's own
explicit, deliberately-written log lines (`lead_intake`, the various `*_failed`/`*_error`
events). Redacting after the fact would require correctly recognizing every possible
secret-bearing URL shape in advance, which is a losing, incomplete-by-construction
approach compared to not logging library-internal request details at all.

## Decision Made
- `app/logging_config.py`: `logging.getLogger("httpx").setLevel(logging.WARNING)` and the
  same for `"httpcore"` (the lower-level library `httpx` is built on, which can also emit
  connection-level `INFO` logs) — set once, in `configure_logging()`, alongside the root
  logger setup.
- Slack incoming webhook rotated: old one deactivated in Slack, a new one created and
  updated in both Render and local `.env`.

## Why
This closes the gap generally, not just for the specific URL that happened to be caught
in a screenshot. It also means this project's logs get slightly quieter and more
signal-dense — `httpx`'s own per-request lines were never something this project chose to
emit; they were an artifact of root-logger propagation.

## Trade-offs
- **Less low-level HTTP visibility during debugging.** If a future issue needs to see the
  exact outbound requests `httpx` is making, `httpx`'s logger would need to be
  temporarily lowered back to `INFO` (ideally only in a local debugging session, not left
  that way in production, given exactly what this ADR just found).
- **This was found incidentally, not through deliberate chaos testing** — a reminder that
  a chaos pass's planned experiments don't cover everything; observing real production
  output carefully, even for an unrelated purpose, surfaced something the planned tests
  didn't.
