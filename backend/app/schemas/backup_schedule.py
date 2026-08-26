"""
Scheduled SFTP backup schemas.
"""
from typing import Optional, List
from pydantic import BaseModel, Field, field_validator
from datetime import datetime
from uuid import UUID
import re

_TIME_RE = re.compile(r'^([01]\d|2[0-3]):[0-5]\d$')


def _validate_times(v: List[str]) -> List[str]:
    out = []
    for t in v:
        t = (t or "").strip()
        if not _TIME_RE.match(t):
            raise ValueError(f"Horário inválido (use HH:MM 24h): {t}")
        out.append(t)
    return out


class BackupScheduleBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    is_enabled: bool = True
    schedule_times: List[str] = Field(default_factory=list)
    sftp_host: str = Field(..., min_length=1, max_length=255)
    sftp_port: int = Field(default=22, ge=1, le=65535)
    sftp_username: str = Field(..., min_length=1, max_length=255)
    sftp_password: str = ""
    remote_path: str = Field(default="/{name}/{hostname}-{datetime}.tar.gz", max_length=512)

    @field_validator("schedule_times")
    @classmethod
    def _times(cls, v):
        return _validate_times(v)


class BackupScheduleCreate(BackupScheduleBase):
    pass


class BackupScheduleUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    is_enabled: Optional[bool] = None
    schedule_times: Optional[List[str]] = None
    sftp_host: Optional[str] = Field(None, min_length=1, max_length=255)
    sftp_port: Optional[int] = Field(None, ge=1, le=65535)
    sftp_username: Optional[str] = Field(None, min_length=1, max_length=255)
    sftp_password: Optional[str] = None   # blank/omitted = keep the stored one
    remote_path: Optional[str] = Field(None, max_length=512)

    @field_validator("schedule_times")
    @classmethod
    def _times(cls, v):
        return _validate_times(v) if v is not None else v


class BackupScheduleResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    is_enabled: bool
    schedule_times: List[str]
    sftp_host: str
    sftp_port: int
    sftp_username: str
    has_password: bool = False   # never return the password itself
    remote_path: str
    last_run_at: Optional[datetime] = None
    last_status: Optional[str] = None
    last_message: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class BackupRunResponse(BaseModel):
    success: bool
    status: str
    message: str
