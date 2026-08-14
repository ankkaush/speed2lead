import httpx

from app.adapters.base import StepOutcome, StepResult, classify_http_status
from app.config import settings


async def attempt(lead, client: httpx.AsyncClient) -> StepResult:
    if not settings.slack_webhook_url:
        return StepResult(
            outcome=StepOutcome.PERMANENT_FAILURE,
            error="SLACK_WEBHOOK_URL not configured",
        )

    text = f"New lead: {lead['name']} <{lead['email']}> — {lead['message'][:200]}"

    try:
        response = await client.post(settings.slack_webhook_url, json={"text": text})
    except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError):
        return StepResult(outcome=StepOutcome.TRANSIENT_FAILURE, error="slack request failed: network/timeout")

    outcome = classify_http_status(response.status_code)
    if outcome == StepOutcome.SUCCESS:
        return StepResult(outcome=outcome)
    return StepResult(outcome=outcome, error=f"slack returned {response.status_code}: {response.text[:500]}")
