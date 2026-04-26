"""Add inutilized number ranges table.

Revision ID: 20260426_05
Revises: 20260426_04
Create Date: 2026-04-26 16:40:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260426_05"
down_revision = "20260426_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inutilized_number_ranges",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("emitter_id", sa.String(length=36), nullable=False),
        sa.Column("document_type", sa.String(length=64), nullable=False),
        sa.Column("establishment", sa.String(length=3), nullable=False),
        sa.Column("point", sa.String(length=3), nullable=False),
        sa.Column("numero_desde", sa.Integer(), nullable=False),
        sa.Column("numero_hasta", sa.Integer(), nullable=False),
        sa.Column("timbrado", sa.String(length=8), nullable=False),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("sifen_protocol", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["emitter_id"],
            ["emitters.id"],
            name="fk_inutilized_ranges_emitter_id_emitters",
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["events.id"],
            name="fk_inutilized_ranges_event_id_events",
        ),
    )
    op.create_index(
        "ix_inutilized_ranges_emitter_tuple",
        "inutilized_number_ranges",
        ["emitter_id", "document_type", "establishment", "point"],
    )


def downgrade() -> None:
    op.drop_index("ix_inutilized_ranges_emitter_tuple", table_name="inutilized_number_ranges")
    op.drop_table("inutilized_number_ranges")
