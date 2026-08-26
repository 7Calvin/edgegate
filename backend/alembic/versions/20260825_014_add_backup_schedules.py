"""add backup_schedules table

Revision ID: 014
Revises: 013
Create Date: 2026-08-25

Scheduled SFTP backup module: a named schedule that uploads a full backup to SFTP at
daily times. Additive; backward-compatible.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '014'
down_revision: Union[str, None] = '013'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'backup_schedules',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('schedule_times', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('sftp_host', sa.String(length=255), nullable=False),
        sa.Column('sftp_port', sa.Integer(), nullable=False, server_default='22'),
        sa.Column('sftp_username', sa.String(length=255), nullable=False),
        sa.Column('sftp_password', sa.String(length=512), nullable=False, server_default=''),
        sa.Column('remote_path', sa.String(length=512), nullable=False,
                  server_default='/{name}/{hostname}-{datetime}.tar.gz'),
        sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_status', sa.String(length=20), nullable=True),
        sa.Column('last_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by_id', postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index('ix_backup_schedules_name', 'backup_schedules', ['name'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_backup_schedules_name', table_name='backup_schedules')
    op.drop_table('backup_schedules')
