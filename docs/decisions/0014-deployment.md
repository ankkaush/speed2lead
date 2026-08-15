# 0014 - Deployment: Render blueprint, shared database, separate prod secret

## Decision
Deploy via a checked-in `render.yaml` blueprint (build/start commands, health check path,
env var names — no values). Reverse the earlier separate-production-database decision and
share the existing Supabase project between dev/test and production, due to a concrete
platform constraint discovered during setup, not a change of principle. Generate a
distinct `WEBHOOK_SIGNING_SECRET` for production rather than reusing the local dev value.

## Context
ADR 0013's planning assumed a separate Supabase project for production, for the same
reason argued there: the automated test suite inserts and deletes rows against whatever
`DATABASE_URL` it's given, which shouldn't be the same data a deployed instance treats as
real. Attempting to create that second project hit a real Supabase free-tier limit: 2
active free projects maximum per organization, and this account already has 2 (this
project's dev/test database, and an unrelated prior project). Creating a third would
require pausing or deleting an existing project, or paying.

## Options Considered

**Resolving the project-limit block**: reuse the existing dev/test project for
production too (chosen, per explicit direction) — versus pausing the unrelated prior
project to free a slot, versus the user freeing a slot manually. Pausing someone's
existing, unrelated project as a side effect of this project's setup is the kind of
irreversible-feeling action that deserves asking first, not deciding silently — asked,
and reusing the existing project was the chosen answer.

**Blueprint vs dashboard-only configuration**: a checked-in `render.yaml` (chosen) —
versus configuring the Web Service entirely through Render's dashboard UI with no
record in the repository. A blueprint means the deploy *shape* (build command, start
command, health check path) is version-controlled and reviewable like any other
configuration in this project, consistent with treating infrastructure decisions as
recorded decisions rather than tribal knowledge in a dashboard only one person has seen.
Secret *values* are deliberately excluded (`sync: false` per variable) — only variable
*names* are declared, same boundary this project has drawn everywhere else between
"structure that's safe to commit" and "values that never are."

**Production signing secret**: generated fresh, separate from the local dev value
(chosen) — versus reusing the same `WEBHOOK_SIGNING_SECRET` in both environments. Sharing
a signing secret across environments means a leak in either one compromises both;
generating independently costs nothing (it's invented locally, not issued by an external
provider — see ADR 0010) and is the standard practice for any environment-scoped secret.

## Decision Made
- `render.yaml`: Python web service, `pip install -r requirements.txt` (not
  `-dev`), `uvicorn app.main:app --host 0.0.0.0 --port $PORT`, health check path `/health`
  — the last of which is what makes Render's deploy gating (ADR 0006) actually mean
  something, since Phase 6 made that endpoint verify real database connectivity.
- Production `DATABASE_URL` is the **same** Supabase project used for local dev and the
  automated test suite, not a separate one.
- Production `WEBHOOK_SIGNING_SECRET` is a distinct value from the local one, generated
  the same way (`secrets.token_hex(32)`).
- `HUBSPOT_ACCESS_TOKEN`/`SLACK_WEBHOOK_URL`/`RESEND_API_KEY`/`SENTRY_DSN` are the same
  values as local dev — these are external provider accounts, not project-scoped
  infrastructure, and creating separate HubSpot/Slack/Resend/Sentry accounts solely to
  mirror a dev/prod split wasn't judged worth the setup cost at this project's scale.

## Why
The blueprint approach costs nothing extra (Render supports it natively) and pays for
itself the moment this deploy configuration needs to be reproduced or reviewed. The
database-sharing reversal is a real, load-bearing trade-off, not a shortcut taken
quietly — it's documented here specifically so it doesn't read as an oversight later.

## Trade-offs
- **The automated test suite now runs directly against what the deployed instance
  considers its real database.** Concretely: running `pytest` locally inserts and
  deletes rows tagged with a distinct test-email prefix/domain
  (`speed-to-lead-test-*@example.com`), cleaned up after every test — collision with real
  lead data is very unlikely given that isolation, but it is no longer structurally
  impossible the way a fully separate database would guarantee. Revisit if this project
  ever handles a real client's production traffic, or if a paid Supabase tier removes the
  project-count constraint that caused this reversal.
- **HubSpot/Slack/Resend/Sentry are also shared** between whatever calls the deployed
  instance and local manual testing — a manual test against the live URL creates a real
  HubSpot contact and posts a real Slack message in the same places production traffic
  would, same as local testing already did throughout Phases 3-7.
