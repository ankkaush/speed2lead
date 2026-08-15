import logging
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

from app.config import settings

logger = logging.getLogger("speed_to_lead")

# Per-client-IP sliding window, in-process (ADR 0010). No Redis: this project runs as
# a single instance, and the primary defense for /leads is the signature check above --
# this is a second layer (protects against a misbehaving/retrying integration, or the
# secret ever leaking), not the main line of defense against a horde of attackers.
#
# Known, accepted simplification: this dict never evicts IPs that stop sending requests,
# so it grows for as long as the process runs. Fine at this project's scale (one
# server-to-server caller, a handful of IPs over the app's lifetime); a public-facing
# limiter serving many distinct IPs would need eviction of stale keys, not just stale
# timestamps within a key.
_request_log: "defaultdict[str, deque]" = defaultdict(deque)


def check_rate_limit(request: Request) -> None:
    client_ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    window_start = now - settings.rate_limit_window_seconds

    log = _request_log[client_ip]
    while log and log[0] < window_start:
        log.popleft()

    if len(log) >= settings.rate_limit_max_requests:
        logger.warning(f"rate_limit_exceeded client_ip={client_ip}")
        raise HTTPException(status_code=429, detail="Too many requests, please slow down")

    log.append(now)
