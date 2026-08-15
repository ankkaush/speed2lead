import json

from app.config import settings
from tests.conftest import TEST_EMAIL_DOMAIN, TEST_EMAIL_LOCAL_PREFIX, signed_post_kwargs


def _payload(email_suffix: str, message: str = "I'd like a quote") -> dict:
    return {
        "name": "Ada Lovelace",
        "email": f"{TEST_EMAIL_LOCAL_PREFIX}{email_suffix}@{TEST_EMAIL_DOMAIN}",
        "phone": "+15551234567",
        "message": message,
        "source": "test-suite",
    }


async def _post(client, payload, idempotency_key=None):
    extra_headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
    kwargs = signed_post_kwargs(payload, extra_headers)
    return await client.post("/leads", **kwargs)


async def test_happy_path_creates_lead_and_attempts_all_steps(client):
    # No HUBSPOT_ACCESS_TOKEN / SLACK_WEBHOOK_URL / RESEND_API_KEY configured in this
    # test environment, so each adapter immediately returns PERMANENT_FAILURE
    # ("not configured") rather than making a real call -- see ADR 0009. That's the
    # correct, intentional behavior to assert here: an unconfigured integration should
    # look like a problem (status "failed"), not silently sit at "pending" forever.
    resp = await _post(client, _payload("happy"))

    assert resp.status_code == 200
    body = resp.json()
    assert body["duplicate"] is False
    assert body["crm_status"] == "failed"
    assert body["notify_status"] == "failed"
    assert body["ack_status"] == "failed"


async def test_missing_email_returns_422(client):
    payload = _payload("missing-email")
    del payload["email"]
    resp = await _post(client, payload)
    assert resp.status_code == 422


async def test_invalid_email_returns_422(client):
    payload = _payload("invalid-email")
    payload["email"] = "not-an-email"
    resp = await _post(client, payload)
    assert resp.status_code == 422


async def test_duplicate_via_client_idempotency_key(client):
    payload = _payload("client-key")

    first = await _post(client, payload, idempotency_key="fixed-test-key-client")
    second = await _post(client, payload, idempotency_key="fixed-test-key-client")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["duplicate"] is False
    assert second.json()["duplicate"] is True
    assert first.json()["id"] == second.json()["id"]


async def test_duplicate_via_fallback_hash_when_no_client_key(client):
    payload = _payload("fallback", message="Same content, resubmitted")

    first = await _post(client, payload)
    second = await _post(client, payload)

    assert first.json()["duplicate"] is False
    assert second.json()["duplicate"] is True
    assert first.json()["id"] == second.json()["id"]


async def test_distinct_message_from_same_sender_is_not_deduped(client):
    base = _payload("distinct")

    first = await _post(client, {**base, "message": "First, distinct inquiry"})
    second = await _post(client, {**base, "message": "Second, different inquiry"})

    assert first.json()["duplicate"] is False
    assert second.json()["duplicate"] is False
    assert first.json()["id"] != second.json()["id"]


async def test_missing_signature_returns_401(client):
    payload = _payload("no-sig")
    resp = await client.post("/leads", json=payload)
    assert resp.status_code == 401


async def test_invalid_signature_returns_401(client):
    payload = _payload("bad-sig")
    resp = await client.post(
        "/leads", json=payload, headers={"X-Webhook-Signature": "0" * 64}
    )
    assert resp.status_code == 401


async def test_signature_tied_to_exact_body(client):
    # Sign one payload, then send a DIFFERENT payload with that signature -- must fail,
    # since a signature over content A shouldn't authenticate content B.
    payload_a = _payload("sig-body-a")
    payload_b = _payload("sig-body-b")
    kwargs = signed_post_kwargs(payload_a)
    kwargs["content"] = json.dumps(payload_b).encode("utf-8")
    resp = await client.post("/leads", **kwargs)
    assert resp.status_code == 401


async def test_rate_limit_exceeded_returns_429(client):
    payload = _payload("rate-limit")
    last_response = None
    for i in range(settings.rate_limit_max_requests + 1):
        last_response = await _post(client, {**payload, "message": f"attempt {i}"})
    assert last_response.status_code == 429
