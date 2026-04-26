"""Add document numbering sequences and document numbering columns.

Revision ID: 20260426_04
Revises: 20260424_03
Create Date: 2026-04-26 12:30:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260426_04"
down_revision = "20260424_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_numbering_sequences",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("emitter_id", sa.String(length=36), nullable=False),
        sa.Column("establishment", sa.String(length=3), nullable=False),
        sa.Column("point", sa.String(length=3), nullable=False),
        sa.Column("document_type", sa.String(length=64), nullable=False),
        sa.Column("last_number", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["emitter_id"],
            ["emitters.id"],
            name="fk_document_numbering_sequences_emitter_id_emitters",
        ),
        sa.UniqueConstraint(
            "emitter_id",
            "establishment",
            "point",
            "document_type",
            name="uq_document_numbering_sequences_tuple",
        ),
    )

    op.add_column("documents", sa.Column("establishment", sa.String(length=3), nullable=True))
    op.add_column("documents", sa.Column("point", sa.String(length=3), nullable=True))
    op.add_column("documents", sa.Column("document_number", sa.Integer(), nullable=True))
    op.create_unique_constraint(
        "uq_documents_emitter_document_number",
        "documents",
        ["emitter_id", "document_type", "establishment", "point", "document_number"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_documents_emitter_document_number",
        "documents",
        type_="unique",
    )
    op.drop_column("documents", "document_number")
    op.drop_column("documents", "point")
    op.drop_column("documents", "establishment")
    op.drop_table("document_numbering_sequences")

