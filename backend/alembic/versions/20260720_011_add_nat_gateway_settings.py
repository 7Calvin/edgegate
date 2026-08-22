"""add_nat_gateway_settings

Adds the single-row `nat_gateway_settings` table so the host-as-NAT-gateway
network (masquerade + IPsec exemptions) can be managed from the admin UI instead
of the NAT_GATEWAY_* env vars. The nat-agent reads this row; the env vars remain a
fallback for deploys that never save via the UI.

Revision ID: 011
Revises: 010
Create Date: 2026-07-20 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '011'
down_revision: Union[str, None] = '010'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'nat_gateway_settings',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('enabled', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('network', sa.String(length=64), nullable=True),
        sa.Column('public_interface', sa.String(length=50), nullable=True),
        sa.Column('exclude_networks', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('nat_gateway_settings')
