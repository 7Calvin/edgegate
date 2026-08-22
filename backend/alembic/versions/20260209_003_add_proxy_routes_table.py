"""add_proxy_routes_table

Revision ID: 003
Revises: 002
Create Date: 2026-02-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '003'
down_revision: Union[str, None] = '002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create enum types
    proxy_route_status = postgresql.ENUM(
        'active', 'inactive', 'error', 'pending',
        name='proxy_route_status', create_type=False
    )
    proxy_route_status.create(op.get_bind(), checkfirst=True)

    ssl_mode = postgresql.ENUM(
        'letsencrypt', 'letsencrypt_dns', 'custom', 'none',
        name='ssl_mode', create_type=False
    )
    ssl_mode.create(op.get_bind(), checkfirst=True)

    health_check_type = postgresql.ENUM(
        'http', 'tcp', 'none',
        name='health_check_type', create_type=False
    )
    health_check_type.create(op.get_bind(), checkfirst=True)

    # Create proxy_routes table
    op.create_table('proxy_routes',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('hostname', sa.String(length=255), nullable=False),
        sa.Column('backend_url', sa.String(length=500), nullable=False),
        sa.Column('path_prefix', sa.String(length=255), nullable=True),
        sa.Column('strip_prefix', sa.Boolean(), nullable=True, server_default='false'),
        sa.Column('ssl_mode', postgresql.ENUM(
            'letsencrypt', 'letsencrypt_dns', 'custom', 'none',
            name='ssl_mode', create_type=False
        ), nullable=True, server_default='letsencrypt'),
        sa.Column('force_https', sa.Boolean(), nullable=True, server_default='true'),
        sa.Column('health_check_type', postgresql.ENUM(
            'http', 'tcp', 'none',
            name='health_check_type', create_type=False
        ), nullable=True, server_default='http'),
        sa.Column('health_check_path', sa.String(length=255), nullable=True, server_default='/'),
        sa.Column('health_check_interval', sa.String(length=20), nullable=True, server_default='30s'),
        sa.Column('pass_host_header', sa.Boolean(), nullable=True, server_default='true'),
        sa.Column('custom_request_headers', sa.Text(), nullable=True),
        sa.Column('custom_response_headers', sa.Text(), nullable=True),
        sa.Column('rate_limit_average', sa.Integer(), nullable=True),
        sa.Column('rate_limit_burst', sa.Integer(), nullable=True),
        sa.Column('status', postgresql.ENUM(
            'active', 'inactive', 'error', 'pending',
            name='proxy_route_status', create_type=False
        ), nullable=True, server_default='pending'),
        sa.Column('is_enabled', sa.Boolean(), nullable=True, server_default='true'),
        sa.Column('last_health_check', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_health_status', sa.Boolean(), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('ssl_certificate_expiry', sa.DateTime(timezone=True), nullable=True),
        sa.Column('ssl_certificate_issuer', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('created_by_id', sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_proxy_routes_name'), 'proxy_routes', ['name'], unique=True)
    op.create_index(op.f('ix_proxy_routes_hostname'), 'proxy_routes', ['hostname'], unique=True)
    op.create_index(op.f('ix_proxy_routes_is_enabled'), 'proxy_routes', ['is_enabled'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_proxy_routes_is_enabled'), table_name='proxy_routes')
    op.drop_index(op.f('ix_proxy_routes_hostname'), table_name='proxy_routes')
    op.drop_index(op.f('ix_proxy_routes_name'), table_name='proxy_routes')
    op.drop_table('proxy_routes')

    # Drop enum types
    postgresql.ENUM(name='health_check_type').drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name='ssl_mode').drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name='proxy_route_status').drop(op.get_bind(), checkfirst=True)
