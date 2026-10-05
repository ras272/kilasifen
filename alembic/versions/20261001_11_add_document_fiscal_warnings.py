"""Keep the fiscal warnings found when a document is created.

For example an emission date more than 120 hours before the transmission:
SIFEN still approves the DE, but with observation 1005 (transmision
extemporanea, MT v150 §6.2.1). Existing documents have no warnings (NULL).

Revision ID: 20261001_11
Revises: 20261001_10
Create Date: 2026-10-01 13:00:00
"""

import sqlalchemy as sa

from alembic import op

revision = "20261001_11"
down_revision = "20261001_10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("fiscal_warnings", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "fiscal_warnings")
