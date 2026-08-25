"""Shared lazy async Redis client (used by login rate limiting, etc.).

The client is created lazily and never blocks app startup: redis.asyncio connects
on first use, and callers are expected to degrade gracefully when Redis is down.
"""
import logging
from typing import Optional

import redis.asyncio as aioredis

from app.core.config import settings

logger = logging.getLogger(__name__)

_client: Optional[aioredis.Redis] = None


def get_redis() -> Optional[aioredis.Redis]:
    """Return the shared async Redis client, or None if it cannot be constructed."""
    global _client
    if _client is None:
        try:
            _client = aioredis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
            )
        except Exception as e:  # pragma: no cover - construction rarely fails
            logger.warning("Could not create Redis client: %s", e)
            return None
    return _client
