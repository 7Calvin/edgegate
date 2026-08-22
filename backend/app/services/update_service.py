"""
Update Service - Proxies system-update operations to the host update-agent.

The heavy lifting (git pull, image rebuild, container recreation, health-gated
rollback) runs in the update-agent, a systemd service on the HOST. It lives
outside the docker-compose lifecycle on purpose: rebuilding/restarting the
backend or frontend mid-update must not kill the update. This service is a thin,
authenticated HTTP client to that agent.

The frontend does NOT poll the backend for update progress (the backend is one
of the containers that restarts). It polls the agent directly through Traefik.
These methods exist for kicking off the update and for the version badge.
"""
import logging
from typing import Any, Dict, Optional, Tuple

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class UpdateService:
    def __init__(self) -> None:
        self.agent_url = settings.UPDATE_AGENT_URL.rstrip("/")
        self.agent_token = settings.UPDATE_AGENT_TOKEN

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.agent_token}"}

    async def _get(self, path: str, timeout: float = 15.0) -> Tuple[bool, Any]:
        # Short connect timeout so an unreachable/firewalled agent fails fast
        # instead of hanging the whole read window (the "spins forever" symptom).
        t = httpx.Timeout(timeout, connect=5.0)
        try:
            async with httpx.AsyncClient(timeout=t) as client:
                resp = await client.get(f"{self.agent_url}{path}", headers=self._headers())
                if resp.status_code == 401:
                    return False, "Unauthorized - check UPDATE_AGENT_TOKEN"
                if resp.status_code != 200:
                    return False, f"Update agent returned status {resp.status_code}"
                return True, resp.json()
        except httpx.ConnectError:
            return False, "Cannot connect to update-agent - is it running on the host?"
        except httpx.TimeoutException:
            return False, "Timeout connecting to update-agent"
        except Exception as e:  # noqa: BLE001 - surface any agent error to the caller
            logger.exception("update-agent GET %s failed", path)
            return False, str(e)

    async def _post(self, path: str, payload: Optional[Dict[str, Any]] = None,
                    timeout: float = 30.0) -> Tuple[bool, Any]:
        t = httpx.Timeout(timeout, connect=5.0)
        try:
            async with httpx.AsyncClient(timeout=t) as client:
                resp = await client.post(
                    f"{self.agent_url}{path}", headers=self._headers(), json=payload or {}
                )
                if resp.status_code == 401:
                    return False, "Unauthorized - check UPDATE_AGENT_TOKEN"
                if resp.status_code == 409:
                    # Lock held: an update is already running.
                    return False, resp.json().get("error", "An update is already in progress")
                if resp.status_code not in (200, 202):
                    return False, f"Update agent returned status {resp.status_code}"
                return True, resp.json()
        except httpx.ConnectError:
            return False, "Cannot connect to update-agent - is it running on the host?"
        except httpx.TimeoutException:
            return False, "Timeout connecting to update-agent"
        except Exception as e:  # noqa: BLE001
            logger.exception("update-agent POST %s failed", path)
            return False, str(e)

    async def get_version(self) -> Dict[str, Any]:
        """Current running version + git details. Never raises: the badge must
        render even when the agent is down (e.g. right after an update)."""
        result: Dict[str, Any] = {
            "current": settings.VERSION,
            "git_sha": None,
            "build_date": None,
        }
        ok, data = await self._get("/version", timeout=8.0)
        if ok and isinstance(data, dict):
            result["git_sha"] = data.get("git_sha")
            result["build_date"] = data.get("build_date")
        return result

    async def check_latest(self) -> Tuple[bool, Any]:
        """Fetch upstream and report whether a newer version is available."""
        return await self._get("/latest", timeout=60.0)

    async def list_versions(self) -> Tuple[bool, Any]:
        """Available version tags (newest first) for the update / rollback picker."""
        return await self._get("/tags", timeout=60.0)

    async def start_update(self, ref: Optional[str] = None, backup: bool = True,
                           run_migrations: bool = True) -> Tuple[bool, Any]:
        """Kick off the update. Returns immediately with a job id; progress is
        polled from the agent directly by the frontend."""
        return await self._post(
            "/update",
            {"ref": ref, "backup": backup, "run_migrations": run_migrations},
            timeout=30.0,
        )

    async def get_status(self) -> Tuple[bool, Any]:
        return await self._get("/status", timeout=10.0)

    async def regenerate_openvpn_config(self) -> Tuple[bool, Any]:
        """Regenerate the OpenVPN server.conf from the current template while
        preserving all PKI/certs. Destructive to manual server.conf edits, so
        it is an explicit, separate action (never part of a normal update)."""
        return await self._post("/openvpn/regenerate-config", {}, timeout=30.0)


update_service = UpdateService()
