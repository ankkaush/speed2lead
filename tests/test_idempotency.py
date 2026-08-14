from datetime import datetime, timezone

from app.idempotency import derive_key, resolve_idempotency_key


def _dt(minute: int) -> datetime:
    return datetime(2026, 1, 1, 12, minute, 0, tzinfo=timezone.utc)


def test_derive_key_normalizes_email_and_whitespace():
    key1 = derive_key("Test@Example.com", "Hello there", _dt(0), bucket_minutes=5)
    key2 = derive_key("test@example.com", "  hello   there  ", _dt(0), bucket_minutes=5)
    assert key1 == key2


def test_derive_key_differs_across_time_buckets():
    key1 = derive_key("test@example.com", "hello", _dt(0), bucket_minutes=5)
    key2 = derive_key("test@example.com", "hello", _dt(10), bucket_minutes=5)
    assert key1 != key2


def test_derive_key_same_within_bucket():
    key1 = derive_key("test@example.com", "hello", _dt(0), bucket_minutes=5)
    key2 = derive_key("test@example.com", "hello", _dt(2), bucket_minutes=5)
    assert key1 == key2


def test_derive_key_differs_for_different_message():
    key1 = derive_key("test@example.com", "hello", _dt(0), bucket_minutes=5)
    key2 = derive_key("test@example.com", "goodbye", _dt(0), bucket_minutes=5)
    assert key1 != key2


def test_resolve_prefers_client_key_when_present():
    key, source = resolve_idempotency_key(
        client_key="abc-123",
        email="test@example.com",
        message="hello",
        received_at=_dt(0),
        bucket_minutes=5,
    )
    assert (key, source) == ("abc-123", "client")


def test_resolve_falls_back_when_no_client_key():
    key, source = resolve_idempotency_key(
        client_key=None,
        email="test@example.com",
        message="hello",
        received_at=_dt(0),
        bucket_minutes=5,
    )
    assert source == "derived"
    assert key == derive_key("test@example.com", "hello", _dt(0), bucket_minutes=5)


def test_resolve_falls_back_when_client_key_is_blank():
    key, source = resolve_idempotency_key(
        client_key="   ",
        email="test@example.com",
        message="hello",
        received_at=_dt(0),
        bucket_minutes=5,
    )
    assert source == "derived"
