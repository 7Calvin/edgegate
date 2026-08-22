"""
Proxy Routes - Traefik Reverse Proxy Management
"""
from uuid import UUID
import logging
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.user import User
from app.services.traefik_service import TraefikService
from app.dependencies.auth import require_admin
from app.schemas.proxy_route import (
    ProxyRouteCreate,
    ProxyRouteUpdate,
    ProxyRouteResponse,
    ProxyRouteListResponse,
    TraefikConfigPreview,
    ProxyRouteHealthStatus,
    CertificateListResponse,
    CertificateRenewResponse,
)
from app.schemas.common import MessageResponse, PaginatedResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()


# ==================== Route CRUD ====================

@router.get("/routes", response_model=PaginatedResponse[ProxyRouteListResponse])
async def list_proxy_routes(
    is_enabled: bool = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all proxy routes (admin only)."""
    service = TraefikService(db)

    routes, total = await service.list_routes(
        is_enabled=is_enabled,
        skip=(page - 1) * per_page,
        limit=per_page,
    )

    return PaginatedResponse.create(
        items=[ProxyRouteListResponse.model_validate(r) for r in routes],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.post("/routes", status_code=status.HTTP_201_CREATED)
async def create_proxy_route(
    data: ProxyRouteCreate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new proxy route (admin only).

    The route will be saved to the database but not applied until
    you call the /apply endpoint.
    """
    service = TraefikService(db)

    route, error = await service.create_route(data, admin)

    if error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error,
        )

    return ProxyRouteResponse.model_validate(route)


@router.get("/routes/{route_id}")
async def get_proxy_route(
    route_id: UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get proxy route details (admin only)."""
    service = TraefikService(db)

    route = await service.get_route_by_id(route_id)

    if not route:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Proxy route not found",
        )

    return ProxyRouteResponse.model_validate(route)


@router.put("/routes/{route_id}")
async def update_proxy_route(
    route_id: UUID,
    data: ProxyRouteUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Update proxy route (admin only).

    After updating, call /apply to write the new configuration.
    """
    service = TraefikService(db)

    route = await service.get_route_by_id(route_id)

    if not route:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Proxy route not found",
        )

    updated_route, error = await service.update_route(route, data, admin)

    if error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error,
        )

    return ProxyRouteResponse.model_validate(updated_route)


@router.delete("/routes/{route_id}", response_model=MessageResponse)
async def delete_proxy_route(
    route_id: UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Delete proxy route (admin only).

    After deleting, call /apply to update the Traefik configuration.
    """
    service = TraefikService(db)

    route = await service.get_route_by_id(route_id)

    if not route:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Proxy route not found",
        )

    success, error = await service.delete_route(route, admin)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error,
        )

    return MessageResponse(message="Proxy route deleted")


# ==================== Config & Apply ====================

@router.post("/apply", response_model=MessageResponse)
async def apply_proxy_config(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Apply proxy configuration (admin only).

    Generates dynamic YAML from database routes and writes it to the
    shared volume. Traefik picks up changes automatically via file watcher.
    """
    service = TraefikService(db)

    success, error = await service.apply_config()

    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=error or "Failed to apply configuration",
        )

    return MessageResponse(message="Configuration applied successfully")


@router.get("/config/preview", response_model=TraefikConfigPreview)
async def preview_proxy_config(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Preview generated Traefik dynamic YAML (admin only).

    Shows what will be written to routes.yml without applying.
    """
    service = TraefikService(db)

    yaml_content = await service.generate_config_yaml()

    return TraefikConfigPreview(yaml_config=yaml_content)


# ==================== Traefik Status ====================

@router.get("/status")
async def get_traefik_status(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get Traefik status via its API (admin only)."""
    service = TraefikService(db)

    return await service.get_traefik_status()


# ==================== Health Checks ====================

@router.post("/health-check")
async def check_all_backends(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Run health check on all enabled backends (admin only)."""
    service = TraefikService(db)

    results = await service.check_all_backends()

    return {"results": results}


@router.post("/routes/{route_id}/health-check")
async def check_route_health(
    route_id: UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Run health check on a specific route's backend (admin only)."""
    service = TraefikService(db)

    route = await service.get_route_by_id(route_id)

    if not route:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Proxy route not found",
        )

    result = await service.check_backend_health(route)

    return result


# ==================== SSL Certificates ====================

@router.get("/certificates", response_model=CertificateListResponse)
async def list_certificates(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    List all SSL certificates from Traefik ACME storage (admin only).

    Shows certificate status, expiry dates, and issuer information.
    """
    service = TraefikService(db)

    return await service.get_certificates()


@router.get("/certificates/{domain}")
async def get_certificate_details(
    domain: str,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get detailed certificate information for a domain (admin only)."""
    service = TraefikService(db)

    cert = await service.get_certificate_details(domain)

    if not cert:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Certificate for '{domain}' not found",
        )

    return cert


@router.post("/certificates/{domain}/renew", response_model=CertificateRenewResponse)
async def renew_certificate(
    domain: str,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Force renewal of a certificate (admin only).

    Removes the certificate from ACME storage so Traefik will
    automatically request a new one on the next request.
    """
    service = TraefikService(db)

    success, message = await service.force_renew_certificate(domain)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message,
        )

    return CertificateRenewResponse(
        success=True,
        message=message,
        domain=domain,
    )


@router.post("/certificates/{domain}/reissue", response_model=CertificateRenewResponse)
async def reissue_certificate(
    domain: str,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Force certificate re-issuance by restarting Traefik (admin only).

    Use when the cert is served from Traefik's memory but is gone from acme.json, so
    the normal renew has nothing to remove. Briefly interrupts all proxied HTTPS.
    """
    service = TraefikService(db)

    success, message = await service.force_reissue_via_restart()

    return CertificateRenewResponse(
        success=success,
        message=message,
        domain=domain,
    )


@router.delete("/certificates/{domain}", response_model=MessageResponse)
async def delete_certificate(
    domain: str,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Delete a certificate from ACME storage and/or manual certs (admin only).

    Permanently removes the certificate. A new one will NOT be auto-requested
    unless the corresponding route still exists and Traefik handles a request.
    """
    service = TraefikService(db)

    success, message = await service.delete_certificate(domain)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message,
        )

    return MessageResponse(message=message)


# ==================== Management Domain ====================

class ManagementDomainResponse(BaseModel):
    domain: str
    ip: str
    ssl_enabled: bool


class ManagementDomainUpdate(BaseModel):
    domain: str


@router.get("/management-domain")
async def get_management_domain(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get the current management panel domain from docker-compose.yml."""
    service = TraefikService(db)
    return service.get_management_domain()


@router.put("/management-domain")
async def update_management_domain(
    data: ManagementDomainUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Update the management panel domain in docker-compose.yml (admin only).

    After updating, services need to be restarted for changes to take effect.
    """
    service = TraefikService(db)

    success, message = service.update_management_domain(data.domain)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message,
        )

    return {"success": True, "message": message, "domain": data.domain}
