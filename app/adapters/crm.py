import httpx

from app.adapters.base import StepOutcome, StepResult, classify_http_status
from app.config import settings

# Batch upsert-by-email (ADR 0009 follow-up): HubSpot enforces unique contact emails, so
# the plain "create contact" endpoint returns 409 for a repeat lead from the same person
# -- previously misclassified as a permanent failure. Upserting by email is the correct
# fix: create on first contact, update in place on every later one, no conflict either way.
_HUBSPOT_UPSERT_URL = "https://api.hubapi.com/crm/v3/objects/contacts/batch/upsert"


async def attempt(lead, client: httpx.AsyncClient) -> StepResult:
    if not settings.hubspot_access_token:
        return StepResult(
            outcome=StepOutcome.PERMANENT_FAILURE,
            error="HUBSPOT_ACCESS_TOKEN not configured",
        )

    payload = {
        "inputs": [
            {
                "idProperty": "email",
                "id": lead["email"],
                "properties": {
                    "email": lead["email"],
                    "firstname": lead["name"],
                    "phone": lead["phone"] or "",
                    "lead_message": lead["message"],
                },
            }
        ]
    }

    try:
        response = await client.post(
            _HUBSPOT_UPSERT_URL,
            json=payload,
            headers={"Authorization": f"Bearer {settings.hubspot_access_token}"},
        )
    except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError):
        return StepResult(outcome=StepOutcome.TRANSIENT_FAILURE, error="hubspot request failed: network/timeout")

    if response.status_code in (200, 201):
        body = response.json()
        results = body.get("results") or []
        if results:
            return StepResult(outcome=StepOutcome.SUCCESS, external_id=results[0].get("id"))
        return StepResult(outcome=StepOutcome.PERMANENT_FAILURE, error=f"hubspot upsert returned no results: {response.text[:500]}")

    if response.status_code == 207:
        # Multi-status: our single input either succeeded or failed individually.
        body = response.json()
        results = body.get("results") or []
        errors = body.get("errors") or []
        if results and not errors:
            return StepResult(outcome=StepOutcome.SUCCESS, external_id=results[0].get("id"))
        return StepResult(
            outcome=StepOutcome.PERMANENT_FAILURE,
            error=f"hubspot upsert partial failure: {errors[:1] if errors else body}",
        )

    outcome = classify_http_status(response.status_code)
    return StepResult(outcome=outcome, error=f"hubspot returned {response.status_code}: {response.text[:500]}")
