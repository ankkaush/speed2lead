# 0018 - Phase 11 reusability review

## Decision
Re-verify ADR 0013's reusability claims by reading the actual current code, not by
trusting the earlier pass — several phases of changes had happened since (Phase 4's CRM
rewrite, Phase 5 security, Phase 6 observability, Phase 9's logging fix). Found one real
gap: the README explained how to swap every provider and the hosting platform, but said
nothing about the database, which reads as "just like the others" when it's actually
structurally different. Fixed with documentation only — no code or architecture changes,
per explicit direction and this project's own "don't over-engineer" principle.

## Context
A reusability claim made once and never re-checked can quietly go stale as code changes
around it. This review re-read `app/leads_repo.py`, `app/db.py`, both migration files,
all three adapters, `app/adapters/base.py`, and `app/config.py` directly, plus grepped
the entire `app/` directory for "supabase" and Render-specific references, rather than
re-stating ADR 0013's conclusions from memory.

## Findings

**CRM, notifications, email** (`app/adapters/{crm,notify,ack}.py`): each still fully
isolated — zero references to any of the three providers exist anywhere outside their
own adapter file. Confirmed by direct file reads, not just search.

**Hosting**: zero Render-specific code in `app/`. The only environment-derived value
touched is `$PORT`, read by `render.yaml`'s start command (deployment config, not
application code) — a convention other platforms share.

**Database — the one place the earlier review's binary framing ("modular" / "not") was
too coarse.** Two separate claims exist and need to be evaluated separately:
- *Which Postgres host* (Supabase vs. any other): zero code changes. Confirmed —
  grepped all of `app/` for "supabase", zero matches. Only `DATABASE_URL` changes.
- *Whether the database engine itself* can be swapped (Postgres vs. MySQL/SQLite/etc.):
  no, not without real rewriting. `app/leads_repo.py` and `db/migrations/*.sql` use
  Postgres-specific SQL (`ON CONFLICT ... DO NOTHING`, `RETURNING`, a native
  `CREATE TYPE ... AS ENUM`, a PL/pgSQL trigger function) and the `asyncpg` driver, which
  only speaks Postgres.

The README's integrations table and its "Replacing or customizing an integration"
section (§6) covered the first four rows (CRM, notifications, email, hosting) but was
silent on the database — an omission that reads as an implicit, incorrect claim of equal
swappability.

## Options Considered

**How to fix the gap**: a short, factual paragraph in README §6 stating both halves of
the database claim explicitly (chosen) — versus abstracting the database layer behind an
interface to make the "not swappable" half technically untrue, versus leaving it
unaddressed. Abstracting the database layer was explicitly rejected per direction and
this project's own recurring principle: there's no second database engine implementation
this project actually needs today, so building one now would be solving a hypothetical
problem, not a real one — the same reasoning ADR 0013 already applied to rejecting a
provider registry for the three adapters.

## Decision Made
Added a "Database portability is two different claims, not one" note to README §6,
stating plainly: any Postgres host works with zero code changes; the Postgres engine
itself does not, and naming the specific SQL features responsible. No code, schema, or
architecture changes.

## Why
The fix matches the size of the actual problem. The code's database coupling was never a
defect — using real SQL features (a native enum, `ON CONFLICT`, `RETURNING`) instead of
an ORM abstraction was a deliberate, documented choice from Phase 3 (ADR 0003) in favor of
visibility and simplicity over premature portability. The gap was purely that the
README's later reusability framing didn't carry that context forward accurately.

## Trade-offs
None beyond the ones already accepted in ADR 0003 (Postgres over an ORM/database-agnostic
layer) and ADR 0013 (a `Protocol` over a provider registry) — this ADR doesn't change
either decision, only makes sure the README states their actual scope correctly.
