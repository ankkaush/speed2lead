import httpx

from app.adapters.base import StepOutcome, StepResult, classify_http_status
from app.config import settings

_RESEND_EMAILS_URL = "https://api.resend.com/emails"


async def attempt(lead, client: httpx.AsyncClient) -> StepResult:
    if not settings.resend_api_key:
        return StepResult(
            outcome=StepOutcome.PERMANENT_FAILURE,
            error="RESEND_API_KEY not configured",
        )

    payload = {
        "from": settings.resend_from_email,
        "to": [lead["email"]],
        "subject": "We received your message",
        "html": f"<p>Hi {lead['name']}, thanks for reaching out — we'll be in touch shortly.</p>",
    }

    try:
        response = await client.post(
            _RESEND_EMAILS_URL,
            json=payload,
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
        )
    except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError):
        return StepResult(outcome=StepOutcome.TRANSIENT_FAILURE, error="resend request failed: network/timeout")

    outcome = classify_http_status(response.status_code)
    if outcome == StepOutcome.SUCCESS:
        return StepResult(outcome=outcome, external_id=response.json().get("id"))
    return StepResult(outcome=outcome, error=f"resend returned {response.status_code}: {response.text[:500]}")
