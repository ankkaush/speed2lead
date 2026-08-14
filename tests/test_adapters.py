import pytest

from app.adapters import ack, crm, notify
from app.adapters.base import StepOutcome, classify_http_status

_LEAD = {
    "id": "00000000-0000-0000-0000-000000000000",
    "name": "Test Lead",
    "email": "test@example.com",
    "phone": "+15551234567",
    "message": "hello",
    "source": "test",
}


@pytest.mark.parametrize(
    "status_code,expected",
    [
        (200, StepOutcome.SUCCESS),
        (201, StepOutcome.SUCCESS),
        (299, StepOutcome.SUCCESS),
        (429, StepOutcome.TRANSIENT_FAILURE),
        (500, StepOutcome.TRANSIENT_FAILURE),
        (503, StepOutcome.TRANSIENT_FAILURE),
        (400, StepOutcome.PERMANENT_FAILURE),
        (401, StepOutcome.PERMANENT_FAILURE),
        (404, StepOutcome.PERMANENT_FAILURE),
    ],
)
def test_classify_http_status(status_code, expected):
    assert classify_http_status(status_code) == expected


# No credentials are configured in this test environment (ADR 0009), so each adapter
# must short-circuit to PERMANENT_FAILURE without attempting a real call — client=None
# below would raise if any adapter tried to actually use it.


async def test_crm_adapter_permanent_failure_when_unconfigured():
    result = await crm.attempt(_LEAD, client=None)
    assert result.outcome == StepOutcome.PERMANENT_FAILURE
    assert "HUBSPOT_ACCESS_TOKEN" in result.error


async def test_notify_adapter_permanent_failure_when_unconfigured():
    result = await notify.attempt(_LEAD, client=None)
    assert result.outcome == StepOutcome.PERMANENT_FAILURE
    assert "SLACK_WEBHOOK_URL" in result.error


async def test_ack_adapter_permanent_failure_when_unconfigured():
    result = await ack.attempt(_LEAD, client=None)
    assert result.outcome == StepOutcome.PERMANENT_FAILURE
    assert "RESEND_API_KEY" in result.error
