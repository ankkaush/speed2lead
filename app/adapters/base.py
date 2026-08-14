from dataclasses import dataclass
from enum import Enum
from typing import Optional


class StepOutcome(str, Enum):
    """The three ways any downstream step (CRM/notify/ack) can end, per ADR 0009.

    A shared classification, not per-adapter ad hoc handling: every adapter maps its own
    provider's response into one of these three, and everything downstream of the
    adapter (persistence, retry eligibility) reacts identically regardless of which
    provider produced the result.
    """

    SUCCESS = "success"
    TRANSIENT_FAILURE = "transient_failure"
    PERMANENT_FAILURE = "permanent_failure"


@dataclass
class StepResult:
    outcome: StepOutcome
    external_id: Optional[str] = None
    error: Optional[str] = None


def classify_http_status(status_code: int) -> StepOutcome:
    """2xx -> success. 429 and 5xx -> transient (retrying may help: rate limit, or the
    provider having a bad moment). Everything else (4xx) -> permanent: our request was
    malformed or unauthorized in a way that won't change on retry without a code/config
    fix."""
    if 200 <= status_code < 300:
        return StepOutcome.SUCCESS
    if status_code == 429 or status_code >= 500:
        return StepOutcome.TRANSIENT_FAILURE
    return StepOutcome.PERMANENT_FAILURE
