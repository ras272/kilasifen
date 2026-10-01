"""Record SIFEN's approval, protocol and messages on each document.

- ``sifen_approved_at``: anchor of the cancellation window (48 h for FE,
  168 h for the other DTE, counted from the approval in SIFEN; MT v150
  §6.2.1 p. 25, §11.6.1 4009/4010 p. 134). It replaces ``updated_at``,
  which every save rewrites.
- ``sifen_protocol``: ``dProtAut`` of the approval (MT v150 PP051 p. 46).
- ``sifen_messages``: every ``gResProc`` of the last answer (code, message).
- ``retryable_server_error``: the document was rejected with 0161/0162
  (server failures, MT v150 §12.2.6 p. 153) and its signed XML is sent again.
- ``timbrado``: ``dNumTim`` of the signed DE, to filter inutilizations by
  timbrado (MT v150 §11.1.1 GEI005; RG 23/2019 Art. 23).

Rows written before this revision keep NULL; the platform then falls back to
a conservative lower bound of the approval (``dFecFirma`` of the signed XML,
or the creation time).

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
    op.add_column(
        "documents",
        sa.Column("sifen_approved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("sifen_protocol", sa.String(length=32), nullable=True),
    )
    op.add_column("documents", sa.Column("sifen_messages", sa.JSON(), nullable=True))
    op.add_column(
        "documents",
        sa.Column(
            "retryable_server_error",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "documents", sa.Column("timbrado", sa.String(length=8), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("documents", "timbrado")
    op.drop_column("documents", "retryable_server_error")
    op.drop_column("documents", "sifen_messages")
    op.drop_column("documents", "sifen_protocol")
    op.drop_column("documents", "sifen_approved_at")
