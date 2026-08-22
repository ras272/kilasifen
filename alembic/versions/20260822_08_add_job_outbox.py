"""Add durable DB-to-RQ job outbox.

Revision ID: 20260822_08
Revises: 20260816_07
Create Date: 2026-08-22 12:00:00
"""

import sqlalchemy as sa

from alembic import op

revision = "20260822_08"
down_revision = "20260816_07"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job_outbox",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("queue_name", sa.String(length=32), nullable=False),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(length=64), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
            name="fk_job_outbox_job_id_jobs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_job_outbox"),
        sa.UniqueConstraint("job_id", name="uq_job_outbox_job_id"),
    )
    op.create_index(
        "ix_job_outbox_dispatchable",
        "job_outbox",
        ["status", "available_at", "locked_until"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_job_outbox_dispatchable", table_name="job_outbox")
    op.drop_table("job_outbox")
