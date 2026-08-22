"""
API v1 Router - Aggregates all route modules
"""
from fastapi import APIRouter

from app.api.v1.routes import auth, users, vpn, firewall, connections, admin, ipsec, proxy, acme, system

api_router = APIRouter()

# Include all route modules
api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
api_router.include_router(users.router, prefix="/users", tags=["Users"])
api_router.include_router(vpn.router, prefix="/vpn", tags=["VPN"])
api_router.include_router(firewall.router, prefix="/firewall", tags=["Firewall"])
api_router.include_router(connections.router, prefix="/connections", tags=["Connections"])
api_router.include_router(admin.router, prefix="/admin", tags=["Admin"])
api_router.include_router(ipsec.router, prefix="/ipsec", tags=["IPsec"])
api_router.include_router(proxy.router, prefix="/proxy", tags=["Reverse Proxy"])
api_router.include_router(acme.router, prefix="/acme", tags=["ACME DNS-01"])
api_router.include_router(system.router, prefix="/system", tags=["System / Update"])
