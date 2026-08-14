import httpx

from app.adapters.base import StepOutcome, StepResult, classify_http_status
from app.config import settings

_HUBSPOT_CONTACTS_URL = "https://api.hubapi.com/crm/v3/objects/contacts"


async def attempt(lead, client: httpx.AsyncClient) -> StepResult:
    if not settings.hubspot_access_token:
        return StepResult(
            outcome=StepOutcome.PERMANENT_FAILURE,
            error="HUBSPOT_ACCESS_TOKEN not configured",
        )

    payload = {
        "properties": {
            "email": lead["email"],
            "firstname": lead["name"],
            "phone": lead["phone"] or "",
        }
    }

    try:
        response = await client.post(
            _HUBSPOT_CONTACTS_URL,
            json=payload,
            headers={"Authorization": f"Bearer {settings.hubspot_access_token}"},
        )
    except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError):
        return StepResult(outcome=StepOutcome.TRANSIENT_FAILURE, error="hubspot request failed: network/timeout")

    if response.status_code == 409:
        # A contact with this email already exists in HubSpot (email must be unique
        # there). Proper handling is a search-then-upsert against the existing contact;
        # not implemented yet — flagged here rather than silently treated as success.
        # Known Phase 4 limitation, follow-up: ADR 0009.
        return StepResult(
            outcome=StepOutcome.PERMANENT_FAILURE,
            error="hubspot contact already exists (409) — upsert not yet implemented",
        )

    outcome = classify_http_status(response.status_code)
    if outcome == StepOutcome.SUCCESS:
        return StepResult(outcome=outcome, external_id=response.json().get("id"))
    return StepResult(outcome=outcome, error=f"hubspot returned {response.status_code}: {response.text[:500]}")
