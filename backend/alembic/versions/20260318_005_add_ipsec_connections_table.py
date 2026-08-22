"""add_ipsec_connections_table

Revision ID: 005
Revises: 004
Create Date: 2026-03-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '005'
down_revision: Union[str, None] = '004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create enum types
    ipsec_status = postgresql.ENUM(
        'active', 'inactive', 'connecting', 'error',
        name='ipsec_status',
        create_type=False,
    )
    ipsec_status.create(op.get_bind(), checkfirst=True)

    ike_version = postgresql.ENUM(
        'ikev1', 'ikev2',
        name='ike_version',
        create_type=False,
    )
    ike_version.create(op.get_bind(), checkfirst=True)

    dpd_action = postgresql.ENUM(
        'restart', 'clear', 'hold', 'none',
        name='dpd_action',
        create_type=False,
    )
    dpd_action.create(op.get_bind(), checkfirst=True)

    # Create table
    op.create_table(
        'ipsec_connections',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        # Local (Left)
        sa.Column('left_ip', sa.String(length=45), nullable=False),
        sa.Column('left_subnet', sa.String(length=500), nullable=False),
        sa.Column('left_id', sa.String(length=100), nullable=False),
        # Remote (Right)
        sa.Column('right_ip', sa.String(length=45), nullable=False),
        sa.Column('right_subnet', sa.String(length=500), nullable=False),
        sa.Column('right_id', sa.String(length=100), nullable=False),
        # Authentication
        sa.Column('auth_method', sa.String(length=20), nullable=True, server_default='psk'),
        sa.Column('psk', sa.Text(), nullable=True),
        # IKE Settings (Phase 1)
        sa.Column(
            'ike_version',
            postgresql.ENUM('ikev1', 'ikev2', name='ike_version', create_type=False),
            nullable=True,
            server_default='ikev2',
        ),
        sa.Column('ike_cipher', sa.String(length=100), nullable=True, server_default='aes256-sha256-modp2048'),
        sa.Column('ike_lifetime', sa.String(length=20), nullable=True, server_default='8h'),
        # ESP Settings (Phase 2)
        sa.Column('esp_cipher', sa.String(length=100), nullable=True, server_default='aes256-sha256'),
        sa.Column('key_lifetime', sa.String(length=20), nullable=True, server_default='1h'),
        # Control settings
        sa.Column('auto_start', sa.Boolean(), nullable=True, server_default='true'),
        sa.Column(
            'dpd_action',
            postgresql.ENUM('restart', 'clear', 'hold', 'none', name='dpd_action', create_type=False),
            nullable=True,
            server_default='restart',
        ),
        # Status
        sa.Column(
            'status',
            postgresql.ENUM('active', 'inactive', 'connecting', 'error', name='ipsec_status', create_type=False),
            nullable=True,
            server_default='inactive',
        ),
        sa.Column('is_enabled', sa.Boolean(), nullable=True, server_default='true'),
        sa.Column('last_status_check', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        # Timestamps
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('created_by_id', sa.UUID(), nullable=True),
        # Constraints
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_ipsec_connections_name'), 'ipsec_connections', ['name'], unique=True)
    op.create_index(op.f('ix_ipsec_connections_is_enabled'), 'ipsec_connections', ['is_enabled'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_ipsec_connections_is_enabled'), table_name='ipsec_connections')
    op.drop_index(op.f('ix_ipsec_connections_name'), table_name='ipsec_connections')
    op.drop_table('ipsec_connections')
    postgresql.ENUM(name='dpd_action').drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name='ike_version').drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name='ipsec_status').drop(op.get_bind(), checkfirst=True)
