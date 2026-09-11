"""add tunnel_name to bandwidth_samples

Revision ID: 016
Revises: 014
Create Date: 2026-09-11

Per-tunnel IPsec throughput. Before this, the sampler stored one aggregate
IPsec row per tick (all tunnels summed), so the dashboard could only ever plot
a single combined IPsec line. This adds a nullable ``tunnel_name`` dimension:
the sampler keeps writing the aggregate row (tunnel_name NULL) AND now writes
one row per tunnel (tunnel_name = StrongSwan connection name), letting the
dashboard offer a per-tunnel selector. OpenVPN rows and all historical rows
stay NULL, so the aggregate/"total" queries are unchanged as long as they
filter tunnel_name IS NULL.

Idempotent: the ADD only runs if the column is missing, tolerating a DB that
already has the column but is still < 016 (e.g. a box that ran this feature
branch before the tagged release). Without the guard, `alembic upgrade head`
raises DuplicateColumn and the backend crash-loops on boot.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '016'
down_revision: Union[str, None] = '014'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDEX_NAME = 'ix_bandwidth_samples_source_tunnel_recorded_at'


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    columns = {c['name'] for c in insp.get_columns('bandwidth_samples')}
    if 'tunnel_name' not in columns:
        op.add_column(
            'bandwidth_samples',
            sa.Column('tunnel_name', sa.String(length=255), nullable=True),
        )

    # Back both the per-tunnel query (source, tunnel_name, recorded_at) and the
    # aggregate query (tunnel_name IS NULL is indexable on the same btree).
    indexes = {ix['name'] for ix in insp.get_indexes('bandwidth_samples')}
    if _INDEX_NAME not in indexes:
        op.create_index(
            _INDEX_NAME,
            'bandwidth_samples',
            ['source', 'tunnel_name', 'recorded_at'],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    indexes = {ix['name'] for ix in insp.get_indexes('bandwidth_samples')}
    if _INDEX_NAME in indexes:
        op.drop_index(_INDEX_NAME, table_name='bandwidth_samples')

    columns = {c['name'] for c in insp.get_columns('bandwidth_samples')}
    if 'tunnel_name' in columns:
        op.drop_column('bandwidth_samples', 'tunnel_name')
