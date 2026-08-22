"""fix_nat_source_network_type

Change nat_rules.source_network from INET to TEXT so it can store a
comma-separated list of IPs/CIDRs (e.g. "10.0.0.1, 192.168.1.0/24"),
matching the ORM model (app/models/firewall.py: source_network = Column(Text)).

The original migration 002 created this column as INET, which rejected every
insert from the API with:
    column "source_network" is of type inet but expression is of type character varying

Revision ID: 006
Revises: 005
Create Date: 2026-06-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '006'
down_revision: Union[str, None] = '005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE nat_rules "
        "ALTER COLUMN source_network TYPE text "
        "USING source_network::text"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE nat_rules "
        "ALTER COLUMN source_network TYPE inet "
        "USING source_network::inet"
    )
