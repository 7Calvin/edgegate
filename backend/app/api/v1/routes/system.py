"""
System Routes - Version info and full-system update orchestration.

The actual update runs in the host update-agent (see UpdateService). These
endpoints let the UI show the running version, check for a newer one, and kick
off an update. Progress is streamed by the frontend polling the agent directly
through Traefik (`/update-agent/status`), because the backend itself restarts
mid-update and cannot be relied upon to report its own progress.
"""
import json
import logging
import os
import shutil
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel
from starlette.background import BackgroundTask

from app.core.config import settings
from app.dependencies.auth import get_current_active_user, require_admin
from app.models.user import User
from app.services.update_service import update_service

router = APIRouter()
logger = logging.getLogger(__name__)


# Collects host metrics from a throwaway container. The backend is itself a
# container and can't see the host directly, but it has the docker socket — so a
# one-shot helper mounts the host /proc, /etc/os-release and / (read-only) and
# prints key=value lines. No host-service or compose change needed.
_HOST_METRICS_SCRIPT = r"""
. /osr 2>/dev/null || true
printf 'os=%s\n' "${PRETTY_NAME:-Linux}"
printf 'hostname=%s\n' "$(cat /hhost 2>/dev/null)"
printf 'uptime=%s\n' "$(cut -d. -f1 /hproc/uptime 2>/dev/null)"
printf 'cpu_cores=%s\n' "$(grep -c ^processor /hproc/cpuinfo 2>/dev/null)"
printf 'private_ip=%s\n' "$(hostname -i 2>/dev/null | tr ' ' '\n' | grep -Ev '^(127\.|172\.1[7-9]\.|172\.2[0-9]\.|172\.3[01]\.|::|$)' | head -1)"
awk '/^MemTotal:/{t=$2}/^MemAvailable:/{a=$2}END{printf "mem_total_kb=%d\nmem_avail_kb=%d\n",t,a}' /hproc/meminfo 2>/dev/null
df -P /hroot 2>/dev/null | awk 'NR==2{gsub(/%/,"",$5); printf "disk_pct=%s\ndisk_total_kb=%s\ndisk_used_kb=%s\n",$5,$2,$3}'
c1=$(awk '/^cpu /{s=0;for(i=2;i<=NF;i++)s+=$i; print s","$5}' /hproc/stat)
sleep 1
c2=$(awk '/^cpu /{s=0;for(i=2;i<=NF;i++)s+=$i; print s","$5}' /hproc/stat)
awk -v a="$c1" -v b="$c2" 'BEGIN{split(a,x,",");split(b,y,",");dt=y[1]-x[1];di=y[2]-x[2]; if(dt>0) printf "cpu_pct=%d\n",(100*(dt-di)/dt); else print "cpu_pct=0"}'
printf 'loadavg=%s\n' "$(cut -d' ' -f1 /hproc/loadavg 2>/dev/null)"
"""


def _collect_host_metrics() -> dict:
    data: dict = {}
    try:
        r = subprocess.run(
            [
                "docker", "run", "--rm", "--entrypoint", "sh",
                "--network", "host",
                "-v", "/proc:/hproc:ro",
                "-v", "/etc/os-release:/osr:ro",
                "-v", "/etc/hostname:/hhost:ro",
                "-v", "/:/hroot:ro",
                "redis:7-alpine", "-c", _HOST_METRICS_SCRIPT,
            ],
            capture_output=True, text=True, timeout=20,
        )
        for line in r.stdout.splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                data[k.strip()] = v.strip()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"host metrics collection failed: {e}")
    return data


@router.get("/info")
async def get_system_info(admin: User = Depends(require_admin)):
    """OS, uptime and live CPU/memory/disk of the host, plus public IP + version."""
    info = {
        "os": None, "hostname": None, "uptime_seconds": None,
        "cpu_pct": None, "cpu_cores": None, "loadavg": None,
        "mem_pct": None, "mem_total_kb": None, "mem_used_kb": None,
        "disk_pct": None, "disk_total_kb": None, "disk_used_kb": None,
        "public_ip": None, "private_ip": None,
        "version": None, "update_available": None,
    }

    try:
        v = await update_service.get_version()
        info["version"] = v.get("current")
    except Exception:  # noqa: BLE001
        pass

    d = _collect_host_metrics()
    info["os"] = d.get("os") or None
    info["hostname"] = d.get("hostname") or None
    info["loadavg"] = d.get("loadavg") or None
    info["private_ip"] = d.get("private_ip") or None
    for k in ("uptime", "cpu_pct", "cpu_cores", "disk_pct", "disk_total_kb", "disk_used_kb"):
        val = d.get(k, "")
        if val.isdigit():
            info["uptime_seconds" if k == "uptime" else k] = int(val)
    try:
        mt = int(d.get("mem_total_kb", "0") or 0)
        ma = int(d.get("mem_avail_kb", "0") or 0)
        if mt > 0:
            info["mem_total_kb"] = mt
            info["mem_used_kb"] = mt - ma
            info["mem_pct"] = round(100 * (mt - ma) / mt)
    except (ValueError, ZeroDivisionError):
        pass

    # Public IP: env override, else best-effort external lookup.
    info["public_ip"] = os.environ.get("VPN_SERVER_PUBLIC_IP") or None
    if not info["public_ip"]:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=4.0) as c:
                resp = await c.get("https://api.ipify.org")
                if resp.status_code == 200:
                    info["public_ip"] = resp.text.strip()
        except Exception:  # noqa: BLE001
            pass

    return info


class UpdateRequest(BaseModel):
    ref: str | None = None          # tag/branch to update to (default: latest tag)
    backup: bool = True             # dump DB + PKI before applying
    run_migrations: bool = True     # run alembic upgrade head after rebuild


@router.get("/version")
async def get_version(user: User = Depends(get_current_active_user)):
    """Running version for the UI badge. Any authenticated user."""
    return await update_service.get_version()


# Curated, self-contained API reference (generated from the OpenAPI spec at build time
# into app/static/api-reference.html). Served ONLY to authenticated users — it replaces
# the public Swagger /docs (disabled in production). The panel opens it via a token-
# authenticated fetch and renders it in an iframe, because browsers don't send the Bearer
# header on plain navigation. include_in_schema=False keeps it out of the spec itself.
_API_REFERENCE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "static", "api-reference.html"
)


@router.get("/api-reference", response_class=HTMLResponse, include_in_schema=False)
async def api_reference(user: User = Depends(require_admin)):
    """Serve the curated API reference page (admin only; hidden from the sidebar)."""
    try:
        with open(_API_REFERENCE_PATH, encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API reference not generated for this build",
        )


_API_REFERENCE_JS_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "static", "api-reference.js"
)


@router.get("/api-reference.js", include_in_schema=False)
async def api_reference_js():
    """Serve the reference page's script as a same-origin EXTERNAL asset. The page is
    rendered in an iframe whose inline scripts are blocked by the app's strict CSP
    (script-src 'self', no 'unsafe-inline'); an external same-origin script is allowed.
    Public — this is generic DOM code (search/tab filtering), no secrets; the HTML with
    the endpoint list stays behind admin auth."""
    try:
        with open(_API_REFERENCE_JS_PATH, encoding="utf-8") as f:
            return Response(content=f.read(), media_type="application/javascript")
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")


@router.get("/update/check")
async def check_for_update(admin: User = Depends(require_admin)):
    """Fetch upstream and report whether a newer version is available."""
    ok, data = await update_service.check_latest()
    if not ok:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=data)
    return data


@router.get("/update/versions")
async def list_update_versions(admin: User = Depends(require_admin)):
    """List available version tags so the admin can update to — or roll back to —
    a specific version."""
    ok, data = await update_service.list_versions()
    if not ok:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=data)
    return data


@router.post("/update")
async def start_update(payload: UpdateRequest, admin: User = Depends(require_admin)):
    """Kick off a full-system update. Returns a job id immediately; poll the
    update-agent (via `/update-agent/status`) for live progress."""
    ok, data = await update_service.start_update(
        ref=payload.ref, backup=payload.backup, run_migrations=payload.run_migrations
    )
    if not ok:
        # Lock held / agent unreachable / bad ref -> 409 so the UI can distinguish
        # "already running" from a hard failure.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=data)
    return data


@router.get("/update/status")
async def get_update_status(admin: User = Depends(require_admin)):
    """Proxied status. Prefer polling the agent directly for resilience; this is
    a convenience endpoint for when the backend is up."""
    ok, data = await update_service.get_status()
    if not ok:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=data)
    return data


@router.post("/openvpn/regenerate-config")
async def regenerate_openvpn_config(admin: User = Depends(require_admin)):
    """Regenerate OpenVPN server.conf from the current template, PRESERVING all
    PKI/certs. Explicit action — updates never touch server.conf automatically."""
    ok, data = await update_service.regenerate_openvpn_config()
    if not ok:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=data)
    return data


@router.get("/backup")
async def download_backup(admin: User = Depends(require_admin)):
    """Create a full backup (DB dump + OpenVPN PKI + config marker) and return it as a
    downloadable .tar.gz. Name-agnostic: the DB is dumped with --no-owner --no-acl and
    the OpenVPN PKI is tarred straight from the container volume, so it restores onto a
    fresh install (see POST /system/restore). Runs via the docker socket the backend
    already has; it does not stop or recreate anything."""
    pg = os.environ.get("POSTGRES_CONTAINER", "edgegate-postgres")
    ovpn = os.environ.get("OPENVPN_CONTAINER", "edgegate-openvpn")
    pg_user, pg_db = settings.POSTGRES_USER, settings.POSTGRES_DB
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    tmp = tempfile.mkdtemp(prefix="egbackup_")
    bdir = os.path.join(tmp, f"backup_{ts}")
    os.makedirs(bdir)
    try:
        # 1) Database — portable dump.
        with open(os.path.join(bdir, "db.sql"), "wb") as f:
            r = subprocess.run(
                ["docker", "exec", pg, "pg_dump", "--no-owner", "--no-acl", "-U", pg_user, pg_db],
                stdout=f, stderr=subprocess.PIPE, timeout=300,
            )
        if r.returncode != 0:
            raise HTTPException(500, f"pg_dump failed: {(r.stderr or b'').decode()[:300]}")

        # 2) OpenVPN PKI/certs from the volume (best effort — a fresh VPN may have none).
        with open(os.path.join(bdir, "openvpn-pki.tar.gz"), "wb") as f:
            subprocess.run(
                ["docker", "exec", ovpn, "sh", "-c",
                 "cd /etc/openvpn && tar -czf - $(ls -d ca.crt server.crt server.key ta.key "
                 "dh.pem server.conf ccd ipp.txt pki 2>/dev/null)"],
                stdout=f, stderr=subprocess.DEVNULL, timeout=120,
            )

        # 3) Manifest.
        with open(os.path.join(bdir, "manifest.json"), "w") as f:
            json.dump({"created_at": ts, "version": settings.VERSION,
                       "postgres_db": pg_db, "postgres_user": pg_user}, f)

        archive = os.path.join(tmp, f"backup_{ts}.tar.gz")
        with tarfile.open(archive, "w:gz") as tf:
            tf.add(bdir, arcname=f"backup_{ts}")
        logger.info("Backup created by admin '%s' (%s)", admin.username, ts)
        return FileResponse(
            archive, media_type="application/gzip",
            filename=f"edgegate-backup_{ts}.tar.gz",
            background=BackgroundTask(shutil.rmtree, tmp, ignore_errors=True),
        )
    except HTTPException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    except Exception as e:  # noqa: BLE001
        shutil.rmtree(tmp, ignore_errors=True)
        raise HTTPException(500, f"backup failed: {e}")


@router.post("/restore")
async def start_restore(
    file: UploadFile = File(...),
    admin: User = Depends(require_admin),
):
    """Upload a backup .tar.gz and restore it. DESTRUCTIVE: drops the DB schema and
    recreates the stack. The restore runs on the host update-agent (detached) — poll
    progress via GET /system/update/status like an update. The uploaded file is staged
    into the host install dir through the docker socket (the backend can't write the
    host filesystem directly)."""
    data = await file.read()
    if not data:
        raise HTTPException(400, "empty file")
    if len(data) > 500 * 1024 * 1024:
        raise HTTPException(413, "backup too large (>500MB)")
    if data[:2] != b"\x1f\x8b":  # gzip magic
        raise HTTPException(400, "not a .tar.gz backup archive")

    compose_dir = os.environ.get("COMPOSE_PROJECT_DIR", "/opt/edgegate")
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    host_path = f"{compose_dir}/backups/ui-restore-{ts}.tar.gz"

    # Stage the uploaded file onto the host via a throwaway container (the backend is
    # containerised and can't write the host fs directly). redis:7-alpine is part of
    # the core stack, so no image pull is needed.
    try:
        proc = subprocess.run(
            ["docker", "run", "--rm", "-i", "--entrypoint", "sh",
             "-v", f"{compose_dir}:/host", "redis:7-alpine",
             "-c", f"mkdir -p /host/backups && cat > '/host/backups/ui-restore-{ts}.tar.gz'"],
            input=data, capture_output=True, timeout=180,
        )
        if proc.returncode != 0:
            raise HTTPException(500, f"failed to stage backup: {(proc.stderr or b'').decode()[:200]}")
    except subprocess.TimeoutExpired:
        raise HTTPException(500, "staging the backup timed out")

    logger.warning("Restore requested by admin '%s' from uploaded backup (%d bytes) -> %s",
                   admin.username, len(data), host_path)
    ok, res = await update_service.start_restore(host_path)
    if not ok:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=res)
    return res
