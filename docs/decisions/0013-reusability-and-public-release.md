# 0013 - Reusability review and public-release readiness

## Decision
Formalize the existing adapter pattern with a `Protocol` (structural typing, zero
runtime cost) rather than building a provider registry or plugin system. Add an MIT
license. Confirm via a full audit (working tree + entire git history) that no secret has
ever been committed, before making the repository public.

## Context
Before making this repository public, three things needed honest answers, not
assumptions carried over from earlier phases: is it actually safe to publish (no
leaked secrets, ever, in history)? Is the "adapter" pattern from ADR 0004/0009 actually
swappable, or just organized that way in spirit? And does a public "free to use and
modify" repository need an explicit license to make that true, not just implied?

## Options Considered

**Public-release audit**: full history scan, not just checking the current working tree
(chosen) — a secret can be deleted in a later commit and still exist permanently in
git's history, retrievable by anyone who clones the repo. Checked every commit's diff
for the specific formats this project's actual secrets take (HubSpot `pat-...` tokens,
Slack webhook URLs, Resend `re_...` keys, the 64-hex-char webhook signing secret,
Postgres connection strings, Sentry DSNs) — not just a generic "secret" keyword search,
which would miss anything not literally named "secret." Result: clean. `.env` was never
tracked in any commit; only `.env.example` (placeholders only) was.

**Reusability mechanism**: a `Protocol` in `app/adapters/base.py` (chosen) — versus a
provider registry with config-driven selection (e.g. `CRM_PROVIDER=hubspot` choosing
between multiple pre-built implementations), versus leaving the existing informal
convention undocumented. Inspected the actual codebase first rather than assuming:
core logic (`pipeline.py`, `leads_repo.py`, `routes/leads.py`, `schemas.py`,
`idempotency.py`, `db.py`) already has zero provider-specific references — HubSpot/
Slack/Resend only ever appear inside `app/adapters/*.py` and as settings field names in
`config.py`. The architecture was already decoupled at the level that matters; a
registry would be solving a problem (choosing between multiple *existing*
implementations) this project doesn't have, since there's only one implementation per
role today. A `Protocol` documents the real, already-true contract (one async function,
`lead` in, `StepResult` out) without adding a mechanism nothing yet uses.

**License**: MIT (chosen) — versus Apache 2.0 (adds an explicit patent grant and
contribution-tracking clauses more relevant to larger multi-contributor projects) or a
custom/no license (leaving "free to use and modify" as an informal claim with no actual
legal force — GitHub's own guidance is explicit that no license means default copyright
applies and no one may legally reuse the code, regardless of what a README says). MIT is
the shortest, most widely understood permissive license, and matches the stated intent
exactly: let anyone use, modify, and redistribute this with attribution.

## Decision Made
- `app/adapters/base.py`: added `StepAdapter` (a `Protocol`), documenting that swapping a
  provider means writing a new module matching this shape and changing one dict entry in
  `app/pipeline.py`, with nothing else in the codebase needing to change.
- `LICENSE`: MIT, copyright to the project owner.
- Full audit performed and passed before proceeding to make the repo public.

## Why
Each of the three questions this ADR answers had a concrete, checkable answer rather
than a reasonable-sounding assumption — the audit could have found a real problem, the
reusability review could have found real coupling, and both were worth actually
verifying before the "public" step became irreversible in the sense that a public
GitHub repo's history is trivially cloneable by anyone from the moment it's pushed,
regardless of anything deleted afterward.

## Trade-offs
- **The `Protocol` is documentation-strength, not enforcement-strength.** Python's
  structural typing means a new adapter module satisfying the shape works correctly at
  runtime without any explicit declaration of intent to implement `StepAdapter` — a type
  checker (mypy, pyright) would catch a mismatched signature; nothing at runtime would.
  Acceptable given this project doesn't currently run a type checker in CI; worth adding
  if that ever changes.
- **No config-driven provider selection exists.** Swapping HubSpot for another CRM is a
  one-line code change (`app/pipeline.py`'s `_STEP_ADAPTERS` dict), not an environment
  variable — a deliberate choice given there's no second implementation to select between
  yet, not a limitation being worked around.
