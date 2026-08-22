"""add ipsec right_ip_backup for HA/failover (swanctl remote_addrs)

Revision ID: 012
Revises: 011
Create Date: 2026-07-22

Adds an optional second remote peer IP to ipsec_connections. When set, the swanctl
config generator emits remote_addrs = [right_ip, right_ip_backup] so the tunnel fails
over natively between the two fixed peer IPs. Nullable / backward-compatible.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '012'
down_revision: Union[str, None] = '011'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'ipsec_connections',
        sa.Column('right_ip_backup', sa.String(length=45), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('ipsec_connections', 'right_ip_backup')
