from tests.conftest import TEST_EMAIL_DOMAIN, TEST_EMAIL_LOCAL_PREFIX, signed_post_kwargs


def _payload(email_suffix: str, **overrides) -> dict:
    base = {
        "name": "Edge Case Test",
        "email": f"{TEST_EMAIL_LOCAL_PREFIX}{email_suffix}@{TEST_EMAIL_DOMAIN}",
        "message": "Testing a boundary condition.",
    }
    base.update(overrides)
    return base


async def test_name_exceeding_max_length_returns_422(client):
    kwargs = signed_post_kwargs(_payload("name-too-long", name="x" * 201))
    resp = await client.post("/leads", **kwargs)
    assert resp.status_code == 422


async def test_message_exceeding_max_length_returns_422(client):
    kwargs = signed_post_kwargs(_payload("message-too-long", message="x" * 5001))
    resp = await client.post("/leads", **kwargs)
    assert resp.status_code == 422


async def test_phone_exceeding_max_length_returns_422(client):
    kwargs = signed_post_kwargs(_payload("phone-too-long", phone="1" * 51))
    resp = await client.post("/leads", **kwargs)
    assert resp.status_code == 422


async def test_empty_name_returns_422(client):
    kwargs = signed_post_kwargs(_payload("empty-name", name=""))
    resp = await client.post("/leads", **kwargs)
    assert resp.status_code == 422


async def test_empty_message_returns_422(client):
    kwargs = signed_post_kwargs(_payload("empty-message", message=""))
    resp = await client.post("/leads", **kwargs)
    assert resp.status_code == 422


async def test_fields_at_exact_max_length_are_accepted(client):
    kwargs = signed_post_kwargs(
        _payload("exact-max-length", name="x" * 200, message="x" * 5000, phone="1" * 50)
    )
    resp = await client.post("/leads", **kwargs)
    assert resp.status_code == 200


async def test_malformed_json_body_returns_422_not_500(client):
    """A caller sending garbage instead of JSON must get a normal validation error, not
    fall through to the global exception handler -- FastAPI's own body-parsing failure
    is a 422 case, not an unhandled-bug case."""
    garbage = b"{this is not valid json"
    import hashlib
    import hmac

    from app.config import settings

    signature = hmac.new(settings.webhook_signing_secret.encode("utf-8"), garbage, hashlib.sha256).hexdigest()
    resp = await client.post(
        "/leads",
        content=garbage,
        headers={"Content-Type": "application/json", "X-Webhook-Signature": signature},
    )
    assert resp.status_code == 422


async def test_unicode_and_emoji_content_is_accepted(client):
    """Not an ASCII-only assumption anywhere in validation, storage, or the downstream
    calls -- a lead's name or message may legitimately contain non-Latin scripts or
    emoji, and none of that should be treated as malformed input."""
    kwargs = signed_post_kwargs(
        _payload(
            "unicode-content",
            name="Zoë Müller 田中太郎",
            message="Iñtërnâtiônàlizætiøn test 🎉 with emoji and àccénts",
        )
    )
    resp = await client.post("/leads", **kwargs)
    assert resp.status_code == 200
    assert resp.json()["duplicate"] is False
