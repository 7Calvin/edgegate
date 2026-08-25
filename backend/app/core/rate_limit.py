"""Login brute-force protection backed by Redis.

Fixed-window failure counters per source IP and per username. If Redis is
unavailable the checks fail OPEN (log a warning and allow) so an infra outage
never locks every operator out — availability is favored over strictness here,
and the panel still has MFA + Trusted-Hosts as additional controls.
"""
import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

from app.core.redis_client import get_redis

logger = logging.getLogger(__name__)

# Windowed failure thresholds for interactive login.
IP_MAX_FAILURES = 20
USER_MAX_FAILURES = 8
WINDOW_SECONDS = 15 * 60


@dataclass
class RateLimitStatus:
    limited: bool
    retry_after: int = 0


def _keys(client_ip: Optional[str], username: Optional[str]) -> List[Tuple[str, int]]:
    keys: List[Tuple[str, int]] = []
    if client_ip:
        keys.append((f"login_fail:ip:{client_ip}", IP_MAX_FAILURES))
    if username:
        keys.append((f"login_fail:user:{username.lower()}", USER_MAX_FAILURES))
    return keys


async def check_login_allowed(client_ip: Optional[str], username: Optional[str]) -> RateLimitStatus:
    """Return whether this login attempt is currently allowed (fails open)."""
    r = get_redis()
    if r is None:
        return RateLimitStatus(limited=False)
    try:
        for key, limit in _keys(client_ip, username):
            count = await r.get(key)
            if count is not None and int(count) >= limit:
                ttl = await r.ttl(key)
                return RateLimitStatus(limited=True, retry_after=max(int(ttl), 1))
    except Exception as e:  # Redis down / transient -> fail open
        logger.warning("Login rate-limit check failed (allowing): %s", e)
    return RateLimitStatus(limited=False)


async def record_login_failure(client_ip: Optional[str], username: Optional[str]) -> None:
    """Increment the failure counters (and set the window TTL on first failure)."""
    r = get_redis()
    if r is None:
        return
    try:
        for key, _ in _keys(client_ip, username):
            n = await r.incr(key)
            if n == 1:
                await r.expire(key, WINDOW_SECONDS)
    except Exception as e:
        logger.warning("Login failure record failed: %s", e)


async def record_login_success(client_ip: Optional[str], username: Optional[str]) -> None:
    """Clear the failure counters after a correct password."""
    r = get_redis()
    if r is None:
        return
    try:
        keys = [k for k, _ in _keys(client_ip, username)]
        if keys:
            await r.delete(*keys)
    except Exception as e:
        logger.warning("Login success reset failed: %s", e)
