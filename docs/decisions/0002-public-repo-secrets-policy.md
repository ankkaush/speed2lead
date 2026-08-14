# 0002 - Public repository and secrets policy

## Decision
Treat this repository as a public portfolio artifact from the very first commit, and
enforce a hard rule that no real secrets or real personal data are ever committed.

## Context
The project is intended to become a public GitHub repository for a portfolio/case study.
Unlike a private internal project, anything committed here is visible to anyone,
indefinitely (even after later deletion, via git history). Retrofitting secret hygiene
after secrets have leaked into history is far more costly (history rewriting, credential
rotation) than establishing the discipline from day one.

## Options Considered
- **Treat as private during development, harden before making public**: lower discipline
  early, risk of an accidental leak going unnoticed until the "make it public" step, and
  the project's own roadmap (Phase 6, Security Hardening) already implies this pattern —
  which is exactly what this ADR overrides.
- **Treat as public from day one**: every commit is written as if it's already visible.

## Decision Made
Public-from-day-one. Concretely:
- No real API keys, passwords, tokens, OAuth secrets, database credentials, or production
  secrets are ever committed.
- No real customer/lead data or personally identifiable information from real users is
  ever committed (this project uses synthetic/test lead data only).
- `.gitignore` and `.env.example` are committed. The real `.env` is local-only, gitignored,
  and never committed.
- `.env.example` lists variable names and a short description/placeholder only — never a
  real value.
- The README documents how to create a local `.env` from `.env.example`.

## Why
This is a standing, project-wide rule enforced at every phase — not a Phase 5/8-only
security task. It removes an entire class of risk (secret leakage via commit history) by
making it structurally impossible under normal workflow, rather than relying on a
late-stage audit to catch it.

## Trade-offs
- Slightly more setup friction per new secret (must remember to add both a real value to
  local `.env` and a placeholder entry to `.env.example`).
- Any provider account used for development (Supabase, HubSpot, Slack, Resend, Sentry)
  must use free/sandbox tiers with disposable test data, not real business accounts, since
  their access tokens will exist on the developer's machine and CI/deploy environment.
