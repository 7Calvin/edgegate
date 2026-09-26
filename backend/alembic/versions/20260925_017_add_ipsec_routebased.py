"""add route-based (XFRM interface) fields to ipsec_connections

Revision ID: 017
Revises: 016
Create Date: 2026-09-25

Option B / route-based IPsec. Adds two columns to ipsec_connections:

  * forwarding_mode  -> 'policy' (default, current behavior: one connection with
                        remote_addrs=[primary,backup]) or 'route' (one connection
                        per peer endpoint bound to its own XFRM if_id, deterministic
                        primary by route metric). Default 'policy' so existing
                        connections keep behaving exactly as before after upgrade.
  * if_id_base       -> base XFRM interface id for route-based connections; the
                        primary path uses if_id_base and the backup uses +1.
                        Nullable (only route-based rows need it), allocated on create.

Idempotent: each ADD only runs if the column is missing, tolerating a DB that
already ran this feature branch before the tagged release (same guard as 016),
so `alembic upgrade head` never raises DuplicateColumn and crash-loops the backend.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '017'
down_revision: Union[str, None] = '016'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    columns = {c['name'] for c in insp.get_columns('ipsec_connections')}

    if 'forwarding_mode' not in columns:
        op.add_column(
            'ipsec_connections',
            sa.Column('forwarding_mode', sa.String(length=10),
                      nullable=False, server_default='policy'),
        )

    if 'if_id_base' not in columns:
        op.add_column(
            'ipsec_connections',
            sa.Column('if_id_base', sa.Integer(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    columns = {c['name'] for c in insp.get_columns('ipsec_connections')}

    if 'if_id_base' in columns:
        op.drop_column('ipsec_connections', 'if_id_base')

    if 'forwarding_mode' in columns:
        op.drop_column('ipsec_connections', 'forwarding_mode')
