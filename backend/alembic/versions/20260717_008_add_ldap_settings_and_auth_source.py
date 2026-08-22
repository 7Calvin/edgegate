"""add_ldap_settings_and_auth_source

Adds Active Directory authentication support:
- `ldap_settings`: single-row runtime config managed from the admin UI.
- `users.auth_source`: marks whether a user is validated locally or against AD.
- `users.password_hash` becomes nullable (AD users have no local password).

Revision ID: 008
Revises: 007
Create Date: 2026-07-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '008'
down_revision: Union[str, None] = '007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- users.auth_source -------------------------------------------------
    auth_source = postgresql.ENUM('local', 'ad', name='auth_source')
    auth_source.create(op.get_bind(), checkfirst=True)
    op.add_column(
        'users',
        sa.Column(
            'auth_source',
            # Type already created above — don't emit CREATE TYPE again.
            postgresql.ENUM('local', 'ad', name='auth_source', create_type=False),
            nullable=False,
            server_default='local',
        ),
    )

    # AD users have no local password
    op.alter_column('users', 'password_hash', existing_type=sa.String(255), nullable=True)

    # --- ldap_settings -----------------------------------------------------
    op.create_table(
        'ldap_settings',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('enabled', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('server', sa.String(length=255), nullable=True),
        sa.Column('port', sa.Integer(), server_default='389', nullable=False),
        sa.Column('bind_dn', sa.String(length=500), nullable=True),
        sa.Column('bind_password', sa.Text(), nullable=True),
        sa.Column('search_base', sa.String(length=500), nullable=True),
        sa.Column('user_attr', sa.String(length=50), server_default='sAMAccountName', nullable=False),
        sa.Column('required_group_dn', sa.String(length=500), nullable=True),
        sa.Column('timeout', sa.Integer(), server_default='5', nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('ldap_settings')

    op.alter_column('users', 'password_hash', existing_type=sa.String(255), nullable=False)
    op.drop_column('users', 'auth_source')

    postgresql.ENUM(name='auth_source').drop(op.get_bind(), checkfirst=True)
