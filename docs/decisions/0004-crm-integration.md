# 0004 - CRM integration: real HubSpot, wired in during Phase 3

## Decision
Build a small CRM adapter interface, and implement it against the real HubSpot API
(via a private app access token) starting in Phase 3 — not a mock, and not deferred.

## Context
The project's learning goals explicitly include real external API integration:
authentication, rate limits, error responses, field mapping, and provider quirks. A mock
CRM would simplify the walking skeleton but would teach none of those lessons where they
matter most (Phase 3-4, where idempotency and partial-failure handling are being designed
against a real downstream dependency).

## Options Considered
- **A — Real HubSpot in Phase 3**: adapter interface (`send_lead(lead) -> CRMResult`) with
  HubSpot as the one concrete implementation from the start. Real bearer-token auth, real
  ~100 req/10s rate limit on the free tier, real error responses, real mapping between the
  lead schema and HubSpot's contact object.
- **B — Mock/adapter first, real HubSpot later**: lower friction to get the walking
  skeleton running, but defers the real-integration lessons and would require reshuffling
  Phase 4 (currently Reliability Hardening, not Integrations) or adding a new phase.

## Decision Made
Option A — real HubSpot, in Phase 3, via a private app access token (not full OAuth).

## Why
A private app token is a static bearer token — enough to teach real external-API auth and
error handling without pulling in OAuth's token-refresh lifecycle, which is a separate,
heavier topic not currently in scope (per the project's own principle: learn OAuth
separately when it becomes relevant, rather than making it an unnecessary dependency now).
HubSpot's free CRM tier has no cost.

## Trade-offs
- Requires a real (free) HubSpot developer account and private app setup before Phase 3
  can be fully exercised end-to-end.
- Tests that exercise the CRM adapter need either a live sandbox account or a stubbed
  HTTP layer in test code — the adapter interface (a `Protocol`/ABC) is exactly what makes
  that swap possible without touching pipeline logic, and doubles as groundwork for
  Phase 11's reusability review (a different CRM becomes a second adapter implementation).
