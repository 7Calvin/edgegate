"""add is_readonly to users

Revision ID: 015
Revises: 014
Create Date: 2026-09-04

Read-only role: an orthogonal boolean grant meaningful only for non-admins. A read-only
principal (human or service account) may reach any read endpoint (GET/HEAD/OPTIONS) but
no mutation. Additive and backward-compatible: default False reproduces today's behavior
exactly (nobody is read-only until an admin flags them), so no backfill is required.

Idempotent: the ADD only runs if the column is missing, tolerating a DB where the column
already exists but alembic_version is still < 015 (e.g. a box that ran a feature branch
before the tagged release). Without the guard, `alembic upgrade head` raises
DuplicateColumn and the backend crash-loops on boot.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '015'
down_revision: Union[str, None] = '014'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    columns = {c['name'] for c in insp.get_columns('users')}
    if 'is_readonly' not in columns:
        op.add_column(
            'users',
            sa.Column('is_readonly', sa.Boolean(), nullable=False, server_default=sa.false()),
        )
        # Drop the server_default so the app-level default governs new rows, matching how
        # the other boolean flags on `users` are declared in the model.
        op.alter_column('users', 'is_readonly', server_default=None)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    columns = {c['name'] for c in insp.get_columns('users')}
    if 'is_readonly' in columns:
        op.drop_column('users', 'is_readonly')
