import json
import logging
import sys
import time

from app.correlation import correlation_id_var


class JsonFormatter(logging.Formatter):
    """Minimal structured logging: one JSON object per line.

    Plain-text logs are hard to search/filter once there's more than one integration
    failing at once (CRM down vs Slack down vs a validation error look identical in a
    free-text log line). JSON-per-line makes every log record filterable/greppable by
    field from day one, without pulling in a logging service yet.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }
        correlation_id = correlation_id_var.get()
        if correlation_id:
            payload["correlation_id"] = correlation_id
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)

    # ADR 0017: httpx logs "HTTP Request: <method> <full URL> ..." at INFO for every
    # call it makes, and that URL can itself be a credential -- Slack's incoming webhook
    # authentication is embedded directly in the URL (unlike HubSpot/Resend, which use an
    # Authorization header httpx never logs). At root-logger INFO, that line was flowing
    # into this app's own structured logs on every Slack call, leaking the webhook URL
    # into Render's persisted log history continuously, not as a one-off mistake.
    # Silenced at the source: httpx/httpcore's own per-request logging isn't something
    # this app added deliberately, and everything it captures that actually matters is
    # already covered by this app's own explicit, deliberately-written log lines.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
