"""
Client IP resolution.

The public entrypoint is Traefik (see docker-compose), which appends the real
peer address to X-Forwarded-For. A client can *prepend* arbitrary values to that
header, so the LEFTMOST entry is attacker-controlled and must never be trusted.
We instead read the entry `TRUSTED_PROXY_COUNT` hops from the right — the address
the outermost trusted proxy actually observed.

This is the anti-spoofing basis for the Trusted Hosts feature: enforcement is
only as trustworthy as the IP we resolve here.
"""
from typing import Optional
from fastapi import Request

from app.core.config import settings


def get_trusted_client_ip(request: Request, trusted_hops: Optional[int] = None) -> Optional[str]:
    """Resolve the real client IP, ignoring client-spoofable X-Forwarded-For entries.

    With ``trusted_hops`` trusted proxies in front of us, the genuine client IP is
    the entry that many positions from the right of X-Forwarded-For. Falls back to
    the raw socket peer when there is no header or no proxies are trusted.
    """
    hops = settings.TRUSTED_PROXY_COUNT if trusted_hops is None else trusted_hops

    if hops > 0:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            parts = [p.strip() for p in forwarded.split(",") if p.strip()]
            if parts:
                # Clamp: if the chain is shorter than expected (misconfig or a
                # request that skipped a proxy), fall back to the leftmost real
                # hop rather than indexing off the end.
                idx = max(0, len(parts) - hops)
                return parts[idx]

    return request.client.host if request.client else None
