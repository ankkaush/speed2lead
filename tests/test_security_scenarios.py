from tests.conftest import TEST_EMAIL_DOMAIN, TEST_EMAIL_LOCAL_PREFIX, signed_post_kwargs


def _payload(email_suffix: str) -> dict:
    return {
        "name": "Security Scenario Test",
        "email": f"{TEST_EMAIL_LOCAL_PREFIX}{email_suffix}@{TEST_EMAIL_DOMAIN}",
        "message": "Testing a security-relevant scenario.",
    }


# The global exception handler (ADR 0010/0012) must never swallow FastAPI/Starlette's
# own handling of HTTPException-based responses -- these tests prove each specific
# failure mode still returns its own distinct body, not the generic
# {"detail": "Internal server error"} the safety net produces.


async def test_validation_error_body_is_not_the_generic_500_shape(client):
    payload = _payload("bypass-422")
    del payload["email"]
    kwargs = signed_post_kwargs(payload)
    resp = await client.post("/leads", **kwargs)

    assert resp.status_code == 422
    # FastAPI's own validation error shape is a list under "detail"; our generic
    # handler's is a fixed string -- these are structurally distinguishable.
    assert isinstance(resp.json()["detail"], list)


async def test_signature_error_body_is_not_the_generic_500_shape(client):
    payload = _payload("bypass-401")
    resp = await client.post("/leads", json=payload)

    assert resp.status_code == 401
    assert resp.json()["detail"] in ("Missing signature", "Invalid signature")
    assert resp.json()["detail"] != "Internal server error"


async def test_rate_limit_error_body_is_not_the_generic_500_shape(client):
    from app.config import settings

    payload = _payload("bypass-429")
    last = None
    for i in range(settings.rate_limit_max_requests + 1):
        kwargs = signed_post_kwargs({**payload, "message": f"attempt {i}"})
        last = await client.post("/leads", **kwargs)

    assert last.status_code == 429
    assert last.json()["detail"] == "Too many requests, please slow down"


async def test_replayed_valid_request_is_accepted_not_rejected(client):
    """Documents the accepted risk from ADR 0012, as a test rather than only a comment:
    the HMAC signature (ADR 0010) has no timestamp or nonce, so a captured valid
    request+signature pair remains valid forever. This test proves that today -- the
    exact same signed request, sent twice, is accepted both times (the second as a
    harmless idempotent duplicate, not rejected as a replay, because no replay
    detection exists). If this test ever starts failing because someone adds replay
    protection, that's a welcome reason to update it, not a regression."""
    payload = _payload("replay-test")
    kwargs = signed_post_kwargs(payload)

    first = await client.post("/leads", **kwargs)
    second = await client.post("/leads", **kwargs)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["duplicate"] is True
