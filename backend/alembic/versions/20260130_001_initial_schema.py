"""Initial schema - all tables

Revision ID: 001
Revises:
Create Date: 2026-01-30

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create enums
    user_type = postgresql.ENUM('human', 'service', 'admin', name='user_type', create_type=False)
    user_type.create(op.get_bind(), checkfirst=True)

    auth_method = postgresql.ENUM('password', 'api_key', 'certificate', name='auth_method', create_type=False)
    auth_method.create(op.get_bind(), checkfirst=True)

    connection_status = postgresql.ENUM('active', 'disconnected', 'banned', name='connection_status', create_type=False)
    connection_status.create(op.get_bind(), checkfirst=True)

    firewall_action = postgresql.ENUM('accept', 'drop', 'reject', 'limit', name='firewall_action', create_type=False)
    firewall_action.create(op.get_bind(), checkfirst=True)

    protocol_type = postgresql.ENUM('tcp', 'udp', 'icmp', 'all', name='protocol_type', create_type=False)
    protocol_type.create(op.get_bind(), checkfirst=True)

    # ==================== Users ====================
    op.create_table(
        'users',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('username', sa.String(50), unique=True, nullable=False, index=True),
        sa.Column('email', sa.String(255), index=True),
        sa.Column('password_hash', sa.String(255), nullable=False),
        sa.Column('user_type', postgresql.ENUM('human', 'service', 'admin', name='user_type', create_type=False), nullable=False, default='human'),
        sa.Column('is_active', sa.Boolean(), default=True, index=True),
        sa.Column('is_admin', sa.Boolean(), default=False),
        # MFA
        sa.Column('mfa_required', sa.Boolean(), default=False, nullable=False),
        sa.Column('mfa_enabled', sa.Boolean(), default=False, nullable=False),
        sa.Column('mfa_secret', sa.String(32)),
        sa.Column('mfa_backup_codes', postgresql.ARRAY(sa.Text()), default=[]),
        # Service Account specific
        sa.Column('service_name', sa.String(100)),
        sa.Column('service_description', sa.Text()),
        sa.Column('api_key_hash', sa.String(64), index=True),
        sa.Column('allowed_source_ips', postgresql.ARRAY(postgresql.INET()), default=[]),
        # Limits and quotas
        sa.Column('max_concurrent_connections', sa.Integer(), default=1),
        sa.Column('bandwidth_limit_mbps', sa.Integer()),
        sa.Column('quota_monthly_gb', sa.Integer()),
        # Timestamps
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column('expires_at', sa.DateTime(timezone=True)),
        sa.Column('last_login_at', sa.DateTime(timezone=True)),
        sa.Column('last_login_ip', postgresql.INET()),
        # Audit
        sa.Column('created_by_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id')),
        # Constraints
        sa.CheckConstraint("user_type != 'service' OR service_name IS NOT NULL", name='valid_service_name'),
        sa.CheckConstraint("NOT (mfa_enabled AND mfa_secret IS NULL)", name='valid_mfa'),
    )

    # ==================== VPN Profiles ====================
    op.create_table(
        'vpn_profiles',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), unique=True, nullable=False),
        # Certificates
        sa.Column('client_cert', sa.Text(), nullable=False),
        sa.Column('client_key', sa.Text(), nullable=False),
        sa.Column('ca_cert', sa.Text(), nullable=False),
        sa.Column('ta_key', sa.Text()),
        # Network configuration
        sa.Column('assigned_ip', postgresql.INET(), unique=True, nullable=False, index=True),
        sa.Column('assigned_ipv6', postgresql.INET()),
        sa.Column('subnet_mask', postgresql.INET(), default='255.255.255.0'),
        # Authentication method
        sa.Column('auth_method', postgresql.ENUM('password', 'api_key', 'certificate', name='auth_method', create_type=False), default='password'),
        # Routes
        sa.Column('allowed_networks', postgresql.ARRAY(postgresql.INET()), default=[]),
        sa.Column('denied_networks', postgresql.ARRAY(postgresql.INET()), default=[]),
        sa.Column('push_routes', postgresql.ARRAY(postgresql.INET()), default=[]),
        # DNS
        sa.Column('push_dns_servers', postgresql.ARRAY(postgresql.INET()), default=[]),
        sa.Column('push_dns_domains', postgresql.ARRAY(sa.Text()), default=[]),
        # Connection settings
        sa.Column('compression', sa.Boolean(), default=False),
        sa.Column('tcp_mode', sa.Boolean(), default=False),
        sa.Column('custom_port', sa.Integer()),
        # Limits
        sa.Column('session_timeout_minutes', sa.Integer()),
        sa.Column('idle_timeout_minutes', sa.Integer(), default=30),
        sa.Column('max_bandwidth_mbps', sa.Integer()),
        # Status
        sa.Column('is_active', sa.Boolean(), default=True, index=True),
        sa.Column('is_revoked', sa.Boolean(), default=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True)),
        sa.Column('revoked_by_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id')),
        sa.Column('revocation_reason', sa.Text()),
        # Statistics
        sa.Column('total_connections', sa.Integer(), default=0),
        sa.Column('total_bytes_sent', sa.BigInteger(), default=0),
        sa.Column('total_bytes_received', sa.BigInteger(), default=0),
        sa.Column('last_connection_at', sa.DateTime(timezone=True)),
        # Timestamps
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    # ==================== Connections ====================
    op.create_table(
        'connections',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('vpn_profile_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('vpn_profiles.id', ondelete='CASCADE'), nullable=True),  # Nullable for simplified mode
        # Connection info
        sa.Column('source_ip', postgresql.INET(), nullable=False),
        sa.Column('vpn_ip', postgresql.INET(), nullable=True),  # Nullable for simplified mode
        # Status
        sa.Column('status', postgresql.ENUM('active', 'disconnected', 'banned', name='connection_status', create_type=False), default='active', index=True),
        # Timing
        sa.Column('connected_at', sa.DateTime(timezone=True), server_default=sa.func.now(), index=True),
        sa.Column('disconnected_at', sa.DateTime(timezone=True)),
        # Duration (calculated at query time, not stored)
        sa.Column('duration_seconds', sa.Integer()),
        # Traffic statistics
        sa.Column('bytes_sent', sa.BigInteger(), default=0),
        sa.Column('bytes_received', sa.BigInteger(), default=0),
        sa.Column('packets_sent', sa.BigInteger(), default=0),
        sa.Column('packets_received', sa.BigInteger(), default=0),
        # Metadata
        sa.Column('client_version', sa.String(50)),
        sa.Column('os_info', sa.String(100)),
        sa.Column('disconnect_reason', sa.Text()),
        # Timestamp
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ==================== Firewall Rules ====================
    op.create_table(
        'firewall_rules',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        # Scope
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), index=True),
        sa.Column('applies_to_service_accounts', sa.Boolean(), default=False),
        sa.Column('applies_to_human_users', sa.Boolean(), default=False),
        # Priority
        sa.Column('priority', sa.Integer(), default=100, index=True),
        # Rule details
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('description', sa.Text()),
        # Action
        sa.Column('action', postgresql.ENUM('accept', 'drop', 'reject', 'limit', name='firewall_action', create_type=False), nullable=False),
        sa.Column('protocol', postgresql.ENUM('tcp', 'udp', 'icmp', 'all', name='protocol_type', create_type=False), default='all'),
        # Source
        sa.Column('source_network', postgresql.INET()),
        sa.Column('source_port_range', sa.String(20)),
        # Destination
        sa.Column('destination_network', postgresql.INET()),
        sa.Column('destination_port_range', sa.String(20)),
        # Rate limiting
        sa.Column('rate_limit_connections_per_second', sa.Integer()),
        # Status
        sa.Column('is_active', sa.Boolean(), default=True, index=True),
        sa.Column('is_system_rule', sa.Boolean(), default=False),
        # Timestamps
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column('created_by_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id')),
        # Constraints
        sa.CheckConstraint("user_id IS NOT NULL OR applies_to_service_accounts OR applies_to_human_users", name='valid_scope'),
    )

    # ==================== Audit Logs ====================
    op.create_table(
        'audit_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        # Who
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), index=True),
        sa.Column('username', sa.String(50)),
        # What
        sa.Column('action', sa.String(100), nullable=False, index=True),
        sa.Column('resource_type', sa.String(50)),
        sa.Column('resource_id', postgresql.UUID(as_uuid=True)),
        # Details
        sa.Column('details', postgresql.JSONB()),
        # Where
        sa.Column('ip_address', postgresql.INET(), index=True),
        sa.Column('user_agent', sa.Text()),
        # When
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), index=True),
        # Severity
        sa.Column('severity', sa.String(20), default='info'),
    )

    # ==================== IP Pool ====================
    op.create_table(
        'ip_pool',
        sa.Column('ip_address', postgresql.INET(), primary_key=True),
        # Allocation
        sa.Column('is_allocated', sa.Boolean(), default=False, index=True),
        sa.Column('allocated_to_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('allocated_at', sa.DateTime(timezone=True)),
        # Reservation
        sa.Column('is_reserved', sa.Boolean(), default=False),
        sa.Column('reserved_for', sa.String(100)),
        # Subnet management
        sa.Column('subnet_id', postgresql.UUID(as_uuid=True)),
        # Timestamp
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ==================== Network Routes ====================
    op.create_table(
        'network_routes',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        # Route details
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('description', sa.Text()),
        # Route configuration
        sa.Column('destination_network', postgresql.INET(), nullable=False),
        sa.Column('gateway_ip', postgresql.INET()),
        sa.Column('interface', sa.String(20)),
        sa.Column('metric', sa.Integer(), default=100),
        # Application
        sa.Column('push_to_clients', sa.Boolean(), default=False),
        sa.Column('applies_to_user_ids', postgresql.ARRAY(postgresql.UUID(as_uuid=True)), default=[]),
        # Status
        sa.Column('is_active', sa.Boolean(), default=True, index=True),
        # Timestamps
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    # ==================== Additional Indexes ====================
    # Composite indexes for common queries
    op.create_index('ix_connections_user_status', 'connections', ['user_id', 'status'])
    op.create_index('ix_connections_vpn_ip_status', 'connections', ['vpn_ip', 'status'])
    op.create_index('ix_audit_logs_user_action', 'audit_logs', ['user_id', 'action'])
    op.create_index('ix_firewall_rules_user_priority', 'firewall_rules', ['user_id', 'priority'])


def downgrade() -> None:
    # Drop indexes
    op.drop_index('ix_firewall_rules_user_priority', table_name='firewall_rules')
    op.drop_index('ix_audit_logs_user_action', table_name='audit_logs')
    op.drop_index('ix_connections_vpn_ip_status', table_name='connections')
    op.drop_index('ix_connections_user_status', table_name='connections')

    # Drop tables in reverse order
    op.drop_table('network_routes')
    op.drop_table('ip_pool')
    op.drop_table('audit_logs')
    op.drop_table('firewall_rules')
    op.drop_table('connections')
    op.drop_table('vpn_profiles')
    op.drop_table('users')

    # Drop enums
    op.execute("DROP TYPE IF EXISTS protocol_type")
    op.execute("DROP TYPE IF EXISTS firewall_action")
    op.execute("DROP TYPE IF EXISTS connection_status")
    op.execute("DROP TYPE IF EXISTS auth_method")
    op.execute("DROP TYPE IF EXISTS user_type")
