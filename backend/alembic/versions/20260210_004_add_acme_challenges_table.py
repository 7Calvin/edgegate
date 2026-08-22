"""add_acme_challenges_table

Revision ID: 004
Revises: 003
Create Date: 2026-02-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '004'
down_revision: Union[str, None] = '003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create enum type
    acme_challenge_status = postgresql.ENUM(
        'pending', 'verified', 'issued', 'failed', 'expired',
        name='acme_challenge_status',
        create_type=False,
    )
    acme_challenge_status.create(op.get_bind(), checkfirst=True)

    # Create table
    op.create_table(
        'acme_challenges',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('proxy_route_id', sa.UUID(), nullable=True),
        sa.Column('domain', sa.String(length=255), nullable=False),
        sa.Column(
            'status',
            postgresql.ENUM(
                'pending', 'verified', 'issued', 'failed', 'expired',
                name='acme_challenge_status',
                create_type=False,
            ),
            nullable=False,
            server_default='pending',
        ),
        sa.Column('txt_record_name', sa.String(length=255), nullable=True),
        sa.Column('txt_record_value', sa.String(length=255), nullable=True),
        sa.Column('acme_order_url', sa.Text(), nullable=True),
        sa.Column('acme_challenge_url', sa.Text(), nullable=True),
        sa.Column('acme_finalize_url', sa.Text(), nullable=True),
        sa.Column('acme_key_thumbprint', sa.String(length=255), nullable=True),
        sa.Column('acme_token', sa.String(length=255), nullable=True),
        sa.Column('certificate_pem', sa.Text(), nullable=True),
        sa.Column('private_key_pem', sa.Text(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by_id', sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(['proxy_route_id'], ['proxy_routes.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_acme_challenges_domain'), 'acme_challenges', ['domain'], unique=False)
    op.create_index(op.f('ix_acme_challenges_status'), 'acme_challenges', ['status'], unique=False)
    op.create_index(op.f('ix_acme_challenges_proxy_route_id'), 'acme_challenges', ['proxy_route_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_acme_challenges_proxy_route_id'), table_name='acme_challenges')
    op.drop_index(op.f('ix_acme_challenges_status'), table_name='acme_challenges')
    op.drop_index(op.f('ix_acme_challenges_domain'), table_name='acme_challenges')
    op.drop_table('acme_challenges')
    postgresql.ENUM(name='acme_challenge_status').drop(op.get_bind(), checkfirst=True)
