"""Add event transport trace columns."""

from alembic import op
import sqlalchemy as sa


revision = "20260424_03"
down_revision = "20260424_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("events", sa.Column("sifen_request_xml", sa.Text(), nullable=True))
    op.add_column("events", sa.Column("sifen_response_raw", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("events", "sifen_response_raw")
    op.drop_column("events", "sifen_request_xml")
