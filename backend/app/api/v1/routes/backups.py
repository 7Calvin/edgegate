"""
Scheduled SFTP backup routes (admin only). A named schedule uploads a full backup
(DB + PKI) to an SFTP server at daily times.
"""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.user import User
from app.models.backup_schedule import BackupSchedule
from app.dependencies.auth import require_admin
from app.schemas.backup_schedule import (
    BackupScheduleCreate,
    BackupScheduleUpdate,
    BackupScheduleResponse,
    BackupRunResponse,
)
from app.schemas.common import MessageResponse
from app.services.backup_schedule_service import BackupScheduleService

router = APIRouter()


def _serialize(s: BackupSchedule) -> BackupScheduleResponse:
    """Response never includes the SFTP password — only a has_password flag."""
    return BackupScheduleResponse(
        id=s.id,
        name=s.name,
        description=s.description,
        is_enabled=s.is_enabled,
        schedule_times=s.schedule_times or [],
        sftp_host=s.sftp_host,
        sftp_port=s.sftp_port,
        sftp_username=s.sftp_username,
        has_password=bool(s.sftp_password),
        remote_path=s.remote_path,
        last_run_at=s.last_run_at,
        last_status=s.last_status,
        last_message=s.last_message,
        created_at=s.created_at,
        updated_at=s.updated_at,
    )


@router.get("", response_model=list[BackupScheduleResponse])
async def list_backups(admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    """List scheduled backups (admin only)."""
    return [_serialize(s) for s in await BackupScheduleService(db).list()]


@router.post("", response_model=BackupScheduleResponse, status_code=status.HTTP_201_CREATED)
async def create_backup(
    data: BackupScheduleCreate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a scheduled backup (admin only)."""
    svc = BackupScheduleService(db)
    if await svc.get_by_name(data.name):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Já existe um backup com esse nome")
    s = BackupSchedule(
        name=data.name,
        description=data.description,
        is_enabled=data.is_enabled,
        schedule_times=data.schedule_times,
        sftp_host=data.sftp_host,
        sftp_port=data.sftp_port,
        sftp_username=data.sftp_username,
        sftp_password=data.sftp_password or "",
        remote_path=data.remote_path,
        created_by_id=admin.id,
    )
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return _serialize(s)


@router.get("/{schedule_id}", response_model=BackupScheduleResponse)
async def get_backup(
    schedule_id: UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    s = await BackupScheduleService(db).get(schedule_id)
    if not s:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Backup não encontrado")
    return _serialize(s)


@router.put("/{schedule_id}", response_model=BackupScheduleResponse)
async def update_backup(
    schedule_id: UUID,
    data: BackupScheduleUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    s = await BackupScheduleService(db).get(schedule_id)
    if not s:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Backup não encontrado")
    payload = data.model_dump(exclude_unset=True)
    # Only change the password when a non-empty one is provided (blank = keep stored).
    pwd = payload.pop("sftp_password", None)
    if pwd:
        s.sftp_password = pwd
    for k, v in payload.items():
        setattr(s, k, v)
    await db.commit()
    await db.refresh(s)
    return _serialize(s)


@router.delete("/{schedule_id}", response_model=MessageResponse)
async def delete_backup(
    schedule_id: UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    s = await BackupScheduleService(db).get(schedule_id)
    if not s:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Backup não encontrado")
    await db.delete(s)
    await db.commit()
    return MessageResponse(message=f"Backup '{s.name}' removido")


@router.post("/{schedule_id}/run", response_model=BackupRunResponse)
async def run_backup_now(
    schedule_id: UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Run the backup now (admin only). Blocks until the upload finishes."""
    s = await BackupScheduleService(db).get(schedule_id)
    if not s:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Backup não encontrado")
    ok, run_status, message = await BackupScheduleService(db).run(s, actor_username=admin.username)
    return BackupRunResponse(success=ok, status=run_status, message=message)
