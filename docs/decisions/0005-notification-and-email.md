# 0005 - Notification and acknowledgement email: Slack incoming webhook + Resend

## Decision
Use a Slack incoming webhook for team notification, and Resend for the lead
acknowledgement email.

## Context
The pipeline needs two more outbound integrations beyond the CRM: notifying the internal
team that a lead arrived, and acknowledging receipt to the lead. Both need to be
proportionate in complexity to what they actually teach — an outbound HTTP call to a
third-party API and one more failure mode to handle in the reliability model — not an
excuse to learn a heavier auth model that isn't otherwise in scope yet.

## Options Considered
- **Slack incoming webhook** (chosen) vs a full OAuth Slack app: a webhook is a single
  secret URL — POST a JSON payload, done. An OAuth app would add an install flow, token
  storage, and scope management for no additional learning value at this stage.
- **Resend** (chosen) vs SendGrid/Postmark for the acknowledgement email: Resend has a
  simple API-key auth model, a workable free tier, and a clean API — comparable in shape
  to the Slack webhook and the CRM's bearer-token auth, so all three outbound integrations
  share the same "one secret + one HTTP POST" pattern rather than each teaching an
  unrelated auth model simultaneously.

## Decision Made
Slack incoming webhook for notification; Resend for acknowledgement email.

## Why
Keeping all three outbound integrations (CRM, Slack, email) proportionate in shape means
the project teaches "how to build a resilient adapter around an outbound HTTP call" once,
generalized, rather than three disconnected lessons. OAuth is deliberately deferred to
whenever it becomes independently relevant, per the project's simplicity principle.

## Trade-offs
- A Slack incoming webhook is scoped to a single channel chosen at webhook-creation time;
  if the project later needs to route notifications to different channels per client
  (relevant to Phase 11 reusability), a heavier Slack app might eventually be justified —
  not now, and only if a concrete requirement demands it.
