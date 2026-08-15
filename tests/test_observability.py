import json
import logging

from app.correlation import correlation_id_var
from app.logging_config import JsonFormatter


async def test_health_check_returns_ok(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_correlation_id_generated_when_not_supplied(client):
    resp = await client.get("/health")
    assert "X-Request-ID" in resp.headers
    assert len(resp.headers["X-Request-ID"]) > 0


async def test_correlation_id_echoes_caller_supplied_value(client):
    resp = await client.get("/health", headers={"X-Request-ID": "my-custom-trace-id"})
    assert resp.headers["X-Request-ID"] == "my-custom-trace-id"


def _make_record() -> logging.LogRecord:
    return logging.LogRecord(
        name="speed_to_lead",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="test message",
        args=(),
        exc_info=None,
    )


def test_json_formatter_includes_correlation_id_when_set():
    token = correlation_id_var.set("test-correlation-123")
    try:
        formatted = json.loads(JsonFormatter().format(_make_record()))
        assert formatted["correlation_id"] == "test-correlation-123"
    finally:
        correlation_id_var.reset(token)


def test_json_formatter_omits_correlation_id_when_not_set():
    formatted = json.loads(JsonFormatter().format(_make_record()))
    assert "correlation_id" not in formatted
