"""
ACME Challenge Schemas for Manual DNS-01 Flow
"""
from typing import Optional
from pydantic import BaseModel, Field, field_validator
from datetime import datetime
from uuid import UUID
import re


class ACMEChallengeRequest(BaseModel):
    """Request to start a DNS-01 challenge"""
    domain: str = Field(..., min_length=1, max_length=255)
    proxy_route_id: Optional[UUID] = None

    @field_validator("domain")
    @classmethod
    def validate_domain(cls, v: str) -> str:
        v = v.strip().lower()
        pattern = r'^(\*\.)?([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$'
        if not re.match(pattern, v):
            raise ValueError("Invalid domain name")
        return v


class ACMEChallengeResponse(BaseModel):
    """Response with DNS challenge instructions"""
    id: UUID
    domain: str
    status: str
    txt_record_name: Optional[str] = None
    txt_record_value: Optional[str] = None
    proxy_route_id: Optional[UUID] = None
    error_message: Optional[str] = None
    expires_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ACMEVerifyResponse(BaseModel):
    """Response after verification attempt"""
    id: UUID
    domain: str
    status: str
    success: bool
    message: str
    error_message: Optional[str] = None


class ACMEChallengeListResponse(BaseModel):
    """Challenge list item"""
    id: UUID
    domain: str
    status: str
    proxy_route_id: Optional[UUID] = None
    expires_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True
