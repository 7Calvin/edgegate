"""add_nat_rules_table

Revision ID: 002
Revises: 001
Create Date: 2026-01-30 19:26:10.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '002'
down_revision: Union[str, None] = '001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create nat_type enum
    nat_type_enum = postgresql.ENUM('dnat', 'snat', name='nat_type', create_type=False)
    nat_type_enum.create(op.get_bind(), checkfirst=True)

    # Create nat_rules table
    op.create_table('nat_rules',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('nat_type', postgresql.ENUM('dnat', 'snat', name='nat_type', create_type=False), nullable=False),
        sa.Column('protocol', postgresql.ENUM('tcp', 'udp', 'icmp', 'all', name='protocol_type', create_type=False), server_default='tcp', nullable=True),
        sa.Column('external_port', sa.Integer(), nullable=False),
        sa.Column('internal_ip', postgresql.INET(), nullable=False),
        sa.Column('internal_port', sa.Integer(), nullable=False),
        sa.Column('source_network', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('created_by_id', sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_nat_rules_is_active'), 'nat_rules', ['is_active'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_nat_rules_is_active'), table_name='nat_rules')
    op.drop_table('nat_rules')

    # Drop enum type
    nat_type_enum = postgresql.ENUM('dnat', 'snat', name='nat_type')
    nat_type_enum.drop(op.get_bind(), checkfirst=True)
