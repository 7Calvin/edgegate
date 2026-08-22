"""add ipsec prefer_backup for manual failover switch

Revision ID: 013
Revises: 012
Create Date: 2026-07-22

When set, the swanctl generator orders remote_addrs = [backup, primary] so charon
prefers the backup endpoint on initiate (manual "switch to backup"). Rollback clears
it. Nullable/defaulted-false, backward-compatible.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '013'
down_revision: Union[str, None] = '012'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'ipsec_connections',
        sa.Column('prefer_backup', sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column('ipsec_connections', 'prefer_backup')
