"""
Database Initialization - Creates tables and initial admin user
"""
import asyncio
import logging
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal, engine, Base
from app.models.user import User, UserType
from app.models.firewall import FirewallRule, FirewallAction, ProtocolType
from app.core.config import settings
from app.core.security import hash_password

logger = logging.getLogger(__name__)


async def create_tables():
    """Create all database tables"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created")


async def create_initial_admin(db: AsyncSession) -> bool:
    """
    Create the initial admin user if it doesn't exist.
    Also creates VPN profile for the admin.

    Returns:
        True if admin was created, False if already exists
    """
    # Check if admin already exists
    result = await db.execute(
        select(User).where(User.username == settings.INITIAL_ADMIN_USERNAME)
    )
    existing_admin = result.scalar_one_or_none()

    if existing_admin:
        logger.info(f"Admin user '{settings.INITIAL_ADMIN_USERNAME}' already exists")

        # Check if admin has VPN profile, create if missing
        from app.models.vpn_profile import VPNProfile
        profile_result = await db.execute(
            select(VPNProfile).where(VPNProfile.user_id == existing_admin.id)
        )
        existing_profile = profile_result.scalar_one_or_none()

        if not existing_profile:
            logger.info(f"Creating missing VPN profile for admin user...")
            from app.services.vpn_service import VPNService
            from app.schemas.vpn import VPNProfileCreate

            vpn_service = VPNService(db)
            vpn_data = VPNProfileCreate(user_id=existing_admin.id)
            profile, vpn_error = await vpn_service.create_profile(existing_admin, vpn_data)

            if vpn_error:
                logger.error(f"Failed to create VPN profile for admin: {vpn_error}")
            else:
                logger.info("VPN profile created for admin")

        return False

    # Create admin user
    admin = User(
        username=settings.INITIAL_ADMIN_USERNAME,
        email=settings.INITIAL_ADMIN_EMAIL,
        password_hash=hash_password(settings.INITIAL_ADMIN_PASSWORD),
        user_type=UserType.ADMIN,
        is_admin=True,
        is_active=True,
        mfa_required=settings.INITIAL_ADMIN_REQUIRE_MFA,
        max_concurrent_connections=5,
    )

    db.add(admin)
    await db.commit()
    await db.refresh(admin)

    logger.info(f"Initial admin user created: {settings.INITIAL_ADMIN_USERNAME}")

    # Create VPN profile for admin
    from app.services.vpn_service import VPNService
    from app.schemas.vpn import VPNProfileCreate

    vpn_service = VPNService(db)
    vpn_data = VPNProfileCreate(user_id=admin.id)
    profile, vpn_error = await vpn_service.create_profile(admin, vpn_data)

    if vpn_error:
        logger.error(f"Failed to create VPN profile for admin: {vpn_error}")
    else:
        logger.info("VPN profile created for admin")

    logger.warning("IMPORTANT: Change the admin password immediately!")

    return True


async def create_default_firewall_rules(db: AsyncSession) -> bool:
    """
    Create default firewall rules if they don't exist.
    Also updates existing rules if needed (e.g., block-private-networks).

    Returns:
        True if rules were created/updated, False if already exist
    """
    # Get push_routes from server config to create block rule for private networks
    from app.services.vpn_service import get_server_config
    server_config = get_server_config()
    push_routes = server_config.get("push_routes", [])

    # Default rules definitions
    default_rules_defs = [
        {
            "name": "allow-icmp",
            "description": "Allow ICMP (ping)",
            "action": FirewallAction.ACCEPT,
            "protocol": ProtocolType.ICMP,
            "priority": 10,
            "is_system_rule": True,
            "applies_to_human_users": True,
            "applies_to_service_accounts": True,
        },
        {
            "name": "allow-dns",
            "description": "Allow DNS queries",
            "action": FirewallAction.ACCEPT,
            "protocol": ProtocolType.UDP,
            "destination_port_range": "53",
            "priority": 20,
            "is_system_rule": True,
            "applies_to_human_users": True,
            "applies_to_service_accounts": True,
        },
        {
            "name": "allow-http-https",
            "description": "Allow HTTP and HTTPS traffic",
            "action": FirewallAction.ACCEPT,
            "protocol": ProtocolType.TCP,
            "destination_port_range": "80,443",
            "priority": 30,
            "is_system_rule": True,
            "applies_to_human_users": True,
            "applies_to_service_accounts": True,
        },
    ]

    # block-client-to-client: enabled by default (quick rule)
    import ipaddress
    from app.core.config import settings
    vpn_net = server_config.get("vpn_network", settings.OPENVPN_NETWORK)
    vpn_mask = server_config.get("vpn_netmask", settings.OPENVPN_NETMASK)
    vpn_network = str(ipaddress.ip_network(f"{vpn_net}/{vpn_mask}", strict=False))

    default_rules_defs.append({
        "name": "block-client-to-client",
        "description": "Block VPN clients from communicating with each other",
        "action": FirewallAction.DROP,
        "protocol": ProtocolType.ALL,
        "source_network": vpn_network,
        "destination_network": vpn_network,
        "priority": 5,
        "is_system_rule": False,
        "applies_to_human_users": True,
        "applies_to_service_accounts": True,
    })

    # allow-internal-network: enabled by default when an internal/NAT network is
    # configured, so VPN clients can reach the private subnet behind this server out
    # of the box (mirrors the Firewall page "Allow Private Network Access" quick rule).
    # Without this DB rule, apply_rules() clears the allow-list on every sync and the
    # internal network becomes unreachable (VPN_FILTER drops it under 10.0.0.0/8).
    internal_networks = None
    if push_routes:
        internal_networks = ",".join(push_routes)
    elif settings.NAT_GATEWAY_NETWORK:
        internal_networks = settings.NAT_GATEWAY_NETWORK
    if internal_networks:
        default_rules_defs.append({
            "name": "allow-internal-network",
            "description": "Allow access to internal network (from push routes)",
            "action": FirewallAction.ACCEPT,
            "protocol": ProtocolType.ALL,
            "destination_network": internal_networks,
            "priority": 50,
            "is_system_rule": False,
            "applies_to_human_users": True,
            "applies_to_service_accounts": True,
        })

    created_count = 0

    # Check each rule and create if missing
    for rule_def in default_rules_defs:
        result = await db.execute(
            select(FirewallRule).where(FirewallRule.name == rule_def["name"])
        )
        existing_rule = result.scalar_one_or_none()

        if not existing_rule:
            # Create new rule
            rule = FirewallRule(**rule_def)
            db.add(rule)
            created_count += 1
            logger.info(f"Created default firewall rule: {rule_def['name']}")

    if created_count > 0:
        await db.commit()
        logger.info(f"Default firewall rules: {created_count} created")
        return True
    else:
        logger.info(f"All default firewall rules already exist")
        return False


async def init_db():
    """Initialize database with tables and initial data"""
    logger.info("Initializing database...")

    # Create tables
    await create_tables()

    # Create initial admin and default firewall rules
    async with AsyncSessionLocal() as db:
        await create_initial_admin(db)
        await create_default_firewall_rules(db)

    logger.info("Database initialization complete")


async def reset_db():
    """
    Drop and recreate all tables.

    WARNING: This will delete all data!
    """
    logger.warning("Resetting database - ALL DATA WILL BE LOST!")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    # Create initial admin
    async with AsyncSessionLocal() as db:
        await create_initial_admin(db)

    logger.info("Database reset complete")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(init_db())
