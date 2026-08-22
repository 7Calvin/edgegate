"""ldap_ntlm_fields

Adds NTLM (signed bind) support to LDAP settings so authentication works against
modern Active Directory that requires integrity checking on the 389 connection
(rejects unsigned simple binds with "strongerAuthRequired"), without LDAPS and
without changing the DC.

- ldap_settings.use_ntlm  : use signed NTLM bind instead of plain simple bind.
- ldap_settings.ad_domain : NetBIOS domain used for the NTLM bind (e.g. CALVIN).

Revision ID: 009
Revises: 008
Create Date: 2026-07-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '009'
down_revision: Union[str, None] = '008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'ldap_settings',
        sa.Column('use_ntlm', sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.add_column(
        'ldap_settings',
        sa.Column('ad_domain', sa.String(length=100), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('ldap_settings', 'ad_domain')
    op.drop_column('ldap_settings', 'use_ntlm')
