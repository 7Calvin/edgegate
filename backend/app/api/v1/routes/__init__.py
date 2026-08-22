"""
API Routes
"""
from app.api.v1.routes import auth, users, vpn, firewall, connections, admin

__all__ = ["auth", "users", "vpn", "firewall", "connections", "admin"]
