from tests.conftest import TEST_EMAIL_DOMAIN, TEST_EMAIL_LOCAL_PREFIX


def _payload(email_suffix: str, message: str = "I'd like a quote") -> dict:
    return {
        "name": "Ada Lovelace",
        "email": f"{TEST_EMAIL_LOCAL_PREFIX}{email_suffix}@{TEST_EMAIL_DOMAIN}",
        "phone": "+15551234567",
        "message": message,
        "source": "test-suite",
    }


async def test_happy_path_creates_lead_with_pending_statuses(client):
    resp = await client.post("/leads", json=_payload("happy"))

    assert resp.status_code == 200
    body = resp.json()
    assert body["duplicate"] is False
    assert body["crm_status"] == "pending"
    assert body["notify_status"] == "pending"
    assert body["ack_status"] == "pending"


async def test_missing_email_returns_422(client):
    payload = _payload("missing-email")
    del payload["email"]
    resp = await client.post("/leads", json=payload)
    assert resp.status_code == 422


async def test_invalid_email_returns_422(client):
    payload = _payload("invalid-email")
    payload["email"] = "not-an-email"
    resp = await client.post("/leads", json=payload)
    assert resp.status_code == 422


async def test_duplicate_via_client_idempotency_key(client):
    payload = _payload("client-key")
    headers = {"Idempotency-Key": "fixed-test-key-client"}

    first = await client.post("/leads", json=payload, headers=headers)
    second = await client.post("/leads", json=payload, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["duplicate"] is False
    assert second.json()["duplicate"] is True
    assert first.json()["id"] == second.json()["id"]


async def test_duplicate_via_fallback_hash_when_no_client_key(client):
    payload = _payload("fallback", message="Same content, resubmitted")

    first = await client.post("/leads", json=payload)
    second = await client.post("/leads", json=payload)

    assert first.json()["duplicate"] is False
    assert second.json()["duplicate"] is True
    assert first.json()["id"] == second.json()["id"]


async def test_distinct_message_from_same_sender_is_not_deduped(client):
    base = _payload("distinct")

    first = await client.post(
        "/leads", json={**base, "message": "First, distinct inquiry"}
    )
    second = await client.post(
        "/leads", json={**base, "message": "Second, different inquiry"}
    )

    assert first.json()["duplicate"] is False
    assert second.json()["duplicate"] is False
    assert first.json()["id"] != second.json()["id"]
