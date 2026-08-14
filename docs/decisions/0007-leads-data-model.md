# 0007 - Leads data model

## Decision
A single `leads` table, with per-downstream-step status columns and an explicit
idempotency key, rather than separate tables per integration or a generic event log.

## Context
Phase 3 needs a data model that supports: persisting a lead exactly once per real
submission event, tracking each downstream integration (CRM, notification, ack email)
independently so one failing doesn't hide the others, and being auditable ("what happened
to this lead, and when"). PII fields need to be identified explicitly at design time
rather than discovered later during a security audit.

## Options Considered
- **Single `leads` table with status columns per step** (chosen): one row per lead, three
  small status enums (`crm_status`, `notify_status`, `ack_status`), each independently
  `pending`/`success`/`failed`. Simple to query ("show me every lead where CRM failed"),
  simple to reason about, no joins needed for the common case.
- **Separate `lead_events`/outbox table**: a generic append-only event log with an event
  type per attempt. More flexible and more "correct" in a formal sense, but adds a layer
  of indirection and query complexity (reconstructing "current status" requires
  aggregating events) that isn't justified at this project's scale — an instance of the
  over-engineering this project is explicitly trying to avoid.

## Decision Made
Single `leads` table. Fields and rationale:

| Field | Purpose |
|---|---|
| `id` (UUID, PK) | Internal identity, independent of any external CRM ID |
| `idempotency_key` (text, UNIQUE, NOT NULL) | Dedup enforcement — see [[0008-idempotency-strategy]] |
| `idempotency_source` ('client' \| 'derived') | Records which strategy produced the key, for debugging |
| `name`, `email`, `phone`, `message` | Lead content — **PII, flagged here explicitly** |
| `source` (nullable) | Which form/campaign; unused now, load-bearing for Phase 11 reusability |
| `received_at` | When the lead actually arrived, distinct from `created_at` |
| `crm_status`, `notify_status`, `ack_status` | Each `pending`/`success`/`failed`, default `pending` |
| `crm_external_id` (nullable) | HubSpot's ID once pushed — prevents re-creating a duplicate contact on retry |
| `crm_error`, `notify_error`, `ack_error` (nullable) | Last failure reason per step, subject to redaction rules (no secrets ever stored here) |
| `created_at`, `updated_at` | Standard audit timestamps |

Deliberately **not** included yet: per-step retry-attempt counters. Nothing in Phase 3
reads them; they belong in Phase 4 (Reliability Hardening) when retry logic exists. Adding
a column later is a trivial migration — including them now would be schema complexity
ahead of need.

## Why
The status-column approach directly implements the reliability pattern established in
Phase 0 discovery: partial failure is visible and recoverable via the database itself,
without a queue or broker. Keeping PII fields explicit in the schema (rather than an
opaque JSON blob) makes the redaction and access-control work in Phase 5 concrete instead
of speculative.

## Trade-offs
- Adding a fourth downstream integration later means another status/error column pair —
  acceptable at this project's scale; would need reconsidering (event log model) if the
  number of integrations grew significantly.
- No column currently stores the raw original payload as submitted — if that's needed for
  debugging/replay later, it should be a deliberate, reviewed addition (given it would
  duplicate PII into a second location), not a default.
