"""Add the emitter fiscal profile (gEmis data declared in the RUC).

Existing emitters get an empty (NULL) profile: they cannot create documents
until they register it through ``PATCH /v1/emitters/{id}``. No value is
invented for them (MT v150 D103-D132: the data must be the one declared in
the RUC).

Revision ID: 20261001_09
Revises: 20260822_08
Create Date: 2026-10-01 12:00:00
"""

import sqlalchemy as sa

from alembic import op

revision = "20261001_09"
down_revision = "20260822_08"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("emitters", sa.Column("fiscal_profile", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("emitters", "fiscal_profile")
