"""add_bandwidth_samples_table

Time-series table backing the dashboard "Throughput · últimas 24h" chart. A
background sampler inserts one snapshot of server-wide cumulative OpenVPN byte
counters per interval; throughput for an interval is the delta between two
consecutive rows.

Revision ID: 007
Revises: 006
Create Date: 2026-07-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '007'
down_revision: Union[str, None] = '006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'bandwidth_samples',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('recorded_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('cum_bytes_sent', sa.BigInteger(), server_default='0', nullable=True),
        sa.Column('cum_bytes_received', sa.BigInteger(), server_default='0', nullable=True),
        sa.Column('active_clients', sa.Integer(), server_default='0', nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_bandwidth_samples_recorded_at'), 'bandwidth_samples', ['recorded_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_bandwidth_samples_recorded_at'), table_name='bandwidth_samples')
    op.drop_table('bandwidth_samples')
