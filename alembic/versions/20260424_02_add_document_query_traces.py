"""Add document query trace columns."""

from alembic import op
import sqlalchemy as sa


revision = "20260424_02"
down_revision = "20260424_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("last_query_request_xml", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("last_query_response_raw", sa.Text(), nullable=True))
    op.add_column(
        "documents",
        sa.Column("last_query_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("documents", "last_query_at")
    op.drop_column("documents", "last_query_response_raw")
    op.drop_column("documents", "last_query_request_xml")
