"""Access-token revocation (logout) via Redis, keyed by the token's `jti`.

Access tokens are stateless JWTs, so "logout" cannot invalidate them on its own.
On logout we store the token's jti with a TTL equal to its remaining lifetime;
get_current_user rejects any token whose jti is present. Fails OPEN if Redis is
unavailable (a revocation outage must not lock everyone out — tokens still expire
on their own).
"""
import logging

from app.core.redis_client import get_redis

logger = logging.getLogger(__name__)

_PREFIX = "revoked_jti:"


async def revoke_jti(jti: str, ttl_seconds: int) -> None:
    if not jti or ttl_seconds <= 0:
        return
    r = get_redis()
    if r is None:
        return
    try:
        await r.setex(_PREFIX + jti, ttl_seconds, "1")
    except Exception as e:
        logger.warning("Could not revoke token jti: %s", e)


async def is_jti_revoked(jti: str) -> bool:
    if not jti:
        return False
    r = get_redis()
    if r is None:
        return False
    try:
        return bool(await r.exists(_PREFIX + jti))
    except Exception as e:  # Redis down -> fail open
        logger.warning("Token revocation check failed (allowing): %s", e)
        return False
