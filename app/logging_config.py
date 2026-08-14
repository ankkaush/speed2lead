import json
import logging
import sys
import time


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
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
