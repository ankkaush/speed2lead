# 0003 - Database: Postgres via Supabase from day one

## Decision
Use Postgres, hosted on Supabase, from the very first commit — no SQLite phase.

## Context
The pipeline needs to persist leads durably, enforce duplicate-processing protection at
the data layer, and reason honestly about transactions and partial-failure states
(Phase 4, Reliability Hardening). Understanding real constraint enforcement and real
transaction semantics is a core learning objective, not an implementation detail.

## Options Considered
- **A — Postgres via Supabase from day one**: real `UNIQUE` constraint enforcement (the
  database, not application code, becomes the source of truth for "has this lead already
  been processed"), real ACID transactions, real multi-connection concurrency behavior,
  hosted so there's no local install/ops burden, zero dev/prod drift, free tier covers
  this project's scale, no migration ever needed.
- **B — SQLite locally, migrate to Postgres later**: fastest possible fully-offline local
  start, but SQLite's weaker type affinity and largely single-writer concurrency model
  would teach a simplified version of concurrency/constraint behavior that would need to
  be partially unlearned later, and creates an unplanned migration exercise not currently
  scoped as a project phase.

## Decision Made
Option A — Postgres via Supabase, from day one.

## Why
Setup cost is effectively equivalent to SQLite (Supabase's free tier removes the ops
burden of running Postgres yourself), while making the idempotency and transaction
lessons in Phase 3-4 authentic against the actual production engine from the first line of
code, rather than against a simplified substitute.

## Trade-offs
- Local development requires network access to Supabase, unlike a fully-offline SQLite
  file — a minor cost given the free tier's reliability and generosity.
- Introduces one more external dependency/account to manage (with its own connection
  string secret, handled per [[0002-public-repo-secrets-policy]]).
