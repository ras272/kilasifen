"""Persist the exact webhook request body.

Revision ID: 20260816_07
Revises: 20260816_06
Create Date: 2026-08-16 22:15:00
"""

import json

import sqlalchemy as sa

from alembic import op

revision = "20260816_07"
down_revision = "20260816_06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "webhook_deliveries",
        sa.Column("request_body", sa.Text(), nullable=True),
    )

    connection = op.get_bind()
    deliveries = sa.table(
        "webhook_deliveries",
        sa.column("id", sa.String(length=36)),
        sa.column("payload_snapshot", sa.JSON()),
        sa.column("request_body", sa.Text()),
    )
    rows = connection.execute(
        sa.select(deliveries.c.id, deliveries.c.payload_snapshot)
    ).all()
    for delivery_id, payload_snapshot in rows:
        body = json.dumps(
            payload_snapshot or {},
            separators=(",", ":"),
            sort_keys=True,
        )
        connection.execute(
            deliveries.update()
            .where(deliveries.c.id == delivery_id)
            .values(request_body=body)
        )


def downgrade() -> None:
    op.drop_column("webhook_deliveries", "request_body")
