"""
Scheduled SFTP backup service — creates a full backup (DB + PKI) and uploads it to
SFTP via paramiko. The background scheduler (main.py) calls is_due()/run().
"""
import os
import json
import shutil
import socket
import asyncio
import tarfile
import tempfile
import subprocess
import logging
from datetime import datetime, timezone
from typing import Optional, Tuple, List
from uuid import UUID

import paramiko
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.backup_schedule import BackupSchedule

logger = logging.getLogger(__name__)


def is_due(schedule: BackupSchedule, now: datetime) -> bool:
    """True if this schedule should run at the current minute and hasn't already.
    `now` is the current time in the scheduler's configured timezone (may be tz-aware);
    minute-level dedup via last_run_at, compared in the same timezone."""
    if not schedule.is_enabled:
        return False
    if now.strftime("%H:%M") not in (schedule.schedule_times or []):
        return False
    last = schedule.last_run_at
    if last is not None:
        if now.tzinfo and last.tzinfo:
            last_cmp = last.astimezone(now.tzinfo)
        else:
            last_cmp = last
        if last_cmp.strftime("%Y%m%d%H%M") == now.strftime("%Y%m%d%H%M"):
            return False
    return True


# ==================== backup + sftp (blocking helpers) ====================

def _create_backup_archive() -> str:
    """Create a DB dump + OpenVPN PKI + manifest tar.gz (mirrors GET /system/backup)
    and return its path. Caller removes the returned file's parent dir."""
    pg = os.environ.get("POSTGRES_CONTAINER", "edgegate-postgres")
    ovpn = os.environ.get("OPENVPN_CONTAINER", "edgegate-openvpn")
    pg_user, pg_db = settings.POSTGRES_USER, settings.POSTGRES_DB
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    tmp = tempfile.mkdtemp(prefix="egbackup_")
    bdir = os.path.join(tmp, f"backup_{ts}")
    os.makedirs(bdir)
    try:
        with open(os.path.join(bdir, "db.sql"), "wb") as f:
            r = subprocess.run(
                ["docker", "exec", pg, "pg_dump", "--no-owner", "--no-acl", "-U", pg_user, pg_db],
                stdout=f, stderr=subprocess.PIPE, timeout=300,
            )
        if r.returncode != 0:
            raise RuntimeError(f"pg_dump falhou: {(r.stderr or b'').decode()[:200]}")
        with open(os.path.join(bdir, "openvpn-pki.tar.gz"), "wb") as f:
            subprocess.run(
                ["docker", "exec", ovpn, "sh", "-c",
                 "cd /etc/openvpn && tar -czf - $(ls -d ca.crt server.crt server.key ta.key "
                 "dh.pem server.conf ccd ipp.txt pki 2>/dev/null)"],
                stdout=f, stderr=subprocess.DEVNULL, timeout=120,
            )
        with open(os.path.join(bdir, "manifest.json"), "w") as f:
            json.dump({"created_at": ts, "version": settings.VERSION,
                       "postgres_db": pg_db, "postgres_user": pg_user}, f)
        archive = os.path.join(tmp, f"backup_{ts}.tar.gz")
        with tarfile.open(archive, "w:gz") as tf:
            tf.add(bdir, arcname=f"backup_{ts}")
        return archive
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise


def _host_hostname() -> str:
    """The Docker HOST's hostname (e.g. 'calvin-v2') — the meaningful device name, like
    FortiGate's %%log.devname%%. socket.gethostname() inside the container only returns
    the container id, so ask the daemon. Falls back to the container hostname."""
    try:
        r = subprocess.run(["docker", "info", "--format", "{{.Name}}"],
                           capture_output=True, text=True, timeout=10)
        name = (r.stdout or "").strip()
        if name:
            return name
    except Exception:  # noqa: BLE001
        pass
    return socket.gethostname()


def _placeholder_now() -> datetime:
    """Current time in SCHEDULER_TIMEZONE so filename {date}/{time}/{datetime} match the
    scheduled trigger time (not the container's UTC). Falls back to naive local."""
    from zoneinfo import ZoneInfo
    try:
        return datetime.now(ZoneInfo(getattr(settings, "SCHEDULER_TIMEZONE", "UTC") or "UTC"))
    except Exception:  # noqa: BLE001
        return datetime.now()


def _expand_placeholders(template: str, name: str) -> str:
    now = _placeholder_now()
    return (template
            .replace("{hostname}", _host_hostname())
            .replace("{name}", name)
            .replace("{date}", now.strftime("%Y%m%d"))
            .replace("{time}", now.strftime("%H%M%S"))
            .replace("{datetime}", now.strftime("%Y%m%d-%H%M%S")))


def _sftp_mkdirs(sftp, path: str) -> None:
    cur = ""
    for part in [p for p in path.split("/") if p]:
        cur = f"{cur}/{part}"
        try:
            sftp.stat(cur)
        except IOError:
            try:
                sftp.mkdir(cur)
            except IOError:
                pass


def _sftp_upload(host: str, port: int, username: str, password: str,
                 local_path: str, remote_path: str) -> None:
    if not host or not username:
        raise ValueError("SFTP host e usuário são obrigatórios")
    transport = paramiko.Transport((host, int(port or 22)))
    try:
        transport.connect(username=username, password=password or "")
        sftp = paramiko.SFTPClient.from_transport(transport)
        remote_dir = os.path.dirname(remote_path)
        if remote_dir and remote_dir != "/":
            _sftp_mkdirs(sftp, remote_dir)
        # confirm=False: skip paramiko's post-upload stat() size check. Upload-only SFTP
        # accounts often lack read/stat permission, so that confirm stat raises
        # [Errno 13] even though the file was written fine.
        sftp.put(local_path, remote_path, confirm=False)
        sftp.close()
    finally:
        transport.close()


# ==================== service ====================

class BackupScheduleService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list(self) -> List[BackupSchedule]:
        res = await self.db.execute(select(BackupSchedule).order_by(BackupSchedule.name))
        return list(res.scalars().all())

    async def get(self, schedule_id: UUID) -> Optional[BackupSchedule]:
        res = await self.db.execute(select(BackupSchedule).where(BackupSchedule.id == schedule_id))
        return res.scalar_one_or_none()

    async def get_by_name(self, name: str) -> Optional[BackupSchedule]:
        res = await self.db.execute(select(BackupSchedule).where(BackupSchedule.name == name))
        return res.scalar_one_or_none()

    async def run(self, schedule: BackupSchedule, actor_username: Optional[str] = None) -> Tuple[bool, str, str]:
        """Create + upload the backup now; persist last_run_at/status/message and write an
        audit entry. `actor_username=None` means the background scheduler ran it (audited
        as '(agendado)'); the run-now route passes the admin's username. Auditing here
        covers the scheduler too, which never hits the HTTP audit middleware.
        Returns (success, status, message)."""
        status, message = "failed", ""
        try:
            remote_tmpl = schedule.remote_path or "/{name}-{datetime}.tar.gz"
            host, port = schedule.sftp_host, schedule.sftp_port
            user, pwd = schedule.sftp_username, schedule.sftp_password

            def _do():
                archive = _create_backup_archive()
                try:
                    remote = _expand_placeholders(remote_tmpl, schedule.name)
                    _sftp_upload(host, port, user, pwd, archive, remote)
                    return f"Backup enviado para {host}:{remote}"
                finally:
                    shutil.rmtree(os.path.dirname(archive), ignore_errors=True)

            message = await asyncio.to_thread(_do)
            status = "success"
        except Exception as e:  # noqa: BLE001
            status, message = "failed", str(e)
            logger.warning(f"Backup schedule '{schedule.name}' failed: {e}")

        schedule.last_run_at = datetime.now(timezone.utc)
        schedule.last_status = status
        schedule.last_message = (message or "")[:1000]
        await self.db.commit()

        try:
            from app.services import audit_service
            await audit_service.record_event(
                action="Backup executado" + ("" if actor_username else " (agendado)"),
                resource_type="config",
                resource_id=schedule.id,
                username=actor_username or "agendador",
                details={"backup": schedule.name, "status": status, "message": (message or "")[:200]},
                severity="info" if status == "success" else "warning",
            )
        except Exception:  # noqa: BLE001 — auditing must never break a backup run
            pass

        return status == "success", status, message
