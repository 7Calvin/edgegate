"""bandwidth_samples source column

Tag each throughput snapshot with its source ("openvpn" | "ipsec") so the
dashboard can plot per-technology throughput. Existing rows are OpenVPN samples.

Revision ID: 010
Revises: 009
Create Date: 2026-07-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '010'
down_revision: Union[str, None] = '009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'bandwidth_samples',
        sa.Column('source', sa.String(length=16), server_default='openvpn', nullable=False),
    )
    # Per-source time queries hit (source, recorded_at); back the throughput query.
    op.create_index(
        op.f('ix_bandwidth_samples_source_recorded_at'),
        'bandwidth_samples',
        ['source', 'recorded_at'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_bandwidth_samples_source_recorded_at'), table_name='bandwidth_samples')
    op.drop_column('bandwidth_samples', 'source')
