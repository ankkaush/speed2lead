# 0006 - Hosting: Render

## Decision
Deploy the FastAPI service to Render.

## Context
The project needs a deployment target for Phase 8 that supports git-push deploys,
environment variable management, log visibility, and a health-check-driven deploy model —
without the operational surface area of managing infrastructure directly.

## Options Considered
- **Render** (chosen): git-push-to-deploy, native env var UI, built-in health-check
  configuration that can point directly at `/health`, dashboard and streamable logs,
  permanently-free tier (with a cold-start delay on idle — a small, useful lesson about
  cold starts in serverless-adjacent hosting).
- **Railway**: comparable simplicity and UI, but its free tier is usage-credit-based
  rather than permanently free, and eventually requires a card on file.
- **Fly.io**: more powerful (edge regions, VM-level control), but requires understanding
  its `fly.toml` config and deploy model more deeply — more operational surface than this
  project's single service needs.
- **AWS** (App Runner / ECS / Elastic Beanstalk): rejected per the project's simplicity
  principle. All would technically work but add IAM, VPC, and console complexity
  disproportionate to a single FastAPI service, and were considered only to be explicitly
  ruled out rather than defaulted to for being "more production-grade."

## Decision Made
Render.

## Why
Render's health-check-driven deploy model matches the project's planned `/health`
endpoint directly, and its free tier doesn't require a card on file or run out of usage
credits — a good fit for a portfolio project meant to stay live and linkable
indefinitely without ongoing cost pressure.

## Trade-offs
- Free-tier services spin down on idle and incur a cold-start delay (~30s) on the next
  request — acceptable for a portfolio/demo project, and itself a concept worth
  understanding and documenting (Phase 9/10) rather than avoiding.
- Less infrastructure control than Fly.io or AWS if a future requirement needs it
  (revisit only if a concrete need arises).
