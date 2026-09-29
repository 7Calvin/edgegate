"""add vendor (peer firewall type) to ipsec_connections

Revision ID: 018
Revises: 017
Create Date: 2026-09-28

Vendor-gating. Adds one column to ipsec_connections:

  * vendor -> peer firewall type ('fortigate' | 'generic'). Drives forwarding_mode,
              dual-link availability and export template via VENDOR_CAPABILITIES.
              server_default 'generic' keeps any pre-migration row on the simple/safe
              path; then we backfill existing route-based rows to 'fortigate' so the
              already-validated connections keep their route-based behaviour.

Idempotent: the ADD only runs if the column is missing (same guard as 016/017), so
`alembic upgrade head` never raises DuplicateColumn and crash-loops the backend.
The backfill is a plain UPDATE keyed on forwarding_mode and is safe to re-run.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '018'
down_revision: Union[str, None] = '017'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    columns = {c['name'] for c in insp.get_columns('ipsec_connections')}

    if 'vendor' not in columns:
        op.add_column(
            'ipsec_connections',
            sa.Column('vendor', sa.String(length=20),
                      nullable=False, server_default='generic'),
        )

    # Backfill: an existing route-based connection was necessarily created for a
    # FortiGate (that's the only vendor that produces route-based), so label it as
    # such; everything else stays 'generic'. Safe to re-run.
    op.execute(
        "UPDATE ipsec_connections SET vendor = 'fortigate' "
        "WHERE forwarding_mode = 'route'"
    )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    columns = {c['name'] for c in insp.get_columns('ipsec_connections')}

    if 'vendor' in columns:
        op.drop_column('ipsec_connections', 'vendor')
