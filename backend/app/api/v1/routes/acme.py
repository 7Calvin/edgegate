"""
ACME DNS-01 Challenge Routes
"""
from uuid import UUID
import logging
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.user import User
from app.models.acme_challenge import ACMEChallengeStatus
from app.services.acme_service import ACMEService
from app.dependencies.auth import require_admin
from app.schemas.acme_challenge import (
    ACMEChallengeRequest,
    ACMEChallengeResponse,
    ACMEVerifyResponse,
    ACMEChallengeListResponse,
)
from app.schemas.common import MessageResponse, PaginatedResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/request-dns", response_model=ACMEChallengeResponse, status_code=status.HTTP_201_CREATED)
async def request_dns_challenge(
    data: ACMEChallengeRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Start a DNS-01 ACME challenge for a domain.

    Returns the TXT record name and value to add to DNS.
    After adding the record, call POST /{challenge_id}/verify to complete.
    """
    logger.info(f"DNS-01 challenge requested for domain={data.domain}, route_id={data.proxy_route_id}")
    service = ACMEService(db)

    challenge, error = await service.request_dns_challenge(
        domain=data.domain,
        route_id=data.proxy_route_id,
        admin=admin,
    )

    if error:
        logger.warning(f"DNS-01 challenge failed for {data.domain}: {error}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error,
        )

    return challenge


@router.post("/{challenge_id}/verify", response_model=ACMEVerifyResponse)
async def verify_dns_challenge(
    challenge_id: UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Verify DNS TXT record and issue certificate.

    Tells the ACME server to check the DNS record.
    If valid, the certificate will be issued and saved.
    """
    service = ACMEService(db)

    challenge = await service.get_challenge(challenge_id)
    if not challenge:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Challenge not found",
        )

    success, message = await service.verify_and_issue(challenge_id)

    # Refresh to get updated status
    await db.refresh(challenge)

    return ACMEVerifyResponse(
        id=challenge.id,
        domain=challenge.domain,
        status=challenge.status.value if hasattr(challenge.status, 'value') else challenge.status,
        success=success,
        message=message,
        error_message=challenge.error_message,
    )


@router.get("/challenges", response_model=PaginatedResponse[ACMEChallengeListResponse])
async def list_challenges(
    challenge_status: str = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all ACME challenges (admin only)."""
    service = ACMEService(db)

    status_enum = None
    if challenge_status:
        try:
            status_enum = ACMEChallengeStatus(challenge_status)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status: {challenge_status}",
            )

    challenges, total = await service.list_challenges(
        status=status_enum,
        skip=(page - 1) * per_page,
        limit=per_page,
    )

    return PaginatedResponse.create(
        items=[ACMEChallengeListResponse.model_validate(c) for c in challenges],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.get("/challenges/{challenge_id}", response_model=ACMEChallengeResponse)
async def get_challenge(
    challenge_id: UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get challenge details (admin only)."""
    service = ACMEService(db)

    challenge = await service.get_challenge(challenge_id)
    if not challenge:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Challenge not found",
        )

    return challenge


@router.delete("/challenges/{challenge_id}", response_model=MessageResponse)
async def delete_challenge(
    challenge_id: UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete a challenge (admin only)."""
    service = ACMEService(db)

    success, error = await service.delete_challenge(challenge_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error,
        )

    return MessageResponse(message="Challenge deleted")
