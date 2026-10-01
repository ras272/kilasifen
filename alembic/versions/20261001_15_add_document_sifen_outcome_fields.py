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
  timbrado (MT v150 §11.1.1 GEI005; RG 23/2019 Art. 23). Rows written
  before this revision get it from the ``dNumTim`` of their signed (or
  generated) XML: a number is inutilized per timbrado (1109, MT v150 §12.4
  C007 p. 161), so a legacy document must not count for every timbrado.
  Only a document never built (no XML) keeps NULL.

Rows written before this revision keep NULL in the other columns; the
platform then falls back to a conservative lower bound of the approval
(``dFecFirma`` of the signed XML, or the creation time).

The revision id was 20261001_09 while the track was developed; it was
renumbered so that it does not collide with another 20261001_09.

Revision ID: 20261001_15
Revises: 20260822_08
Create Date: 2026-10-01 12:00:00
"""

import re

import sqlalchemy as sa

from alembic import op

revision = "20261001_15"
down_revision = "20260822_08"
branch_labels = None
depends_on = None

#: ``dNumTim`` (C004, XSD ``tdNumTim``), with or without a namespace prefix.
_TIMBRADO_PATTERN = re.compile(r"<(?:[A-Za-z_][\w.-]*:)?dNumTim>\s*([0-9]{1,8})\s*<")
_BACKFILL_BATCH = 500


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
    _backfill_timbrado()


def downgrade() -> None:
    op.drop_column("documents", "timbrado")
    op.drop_column("documents", "retryable_server_error")
    op.drop_column("documents", "sifen_messages")
    op.drop_column("documents", "sifen_protocol")
    op.drop_column("documents", "sifen_approved_at")


def _backfill_timbrado() -> None:
    """Copy ``dNumTim`` of each built document into ``timbrado``."""

    connection = op.get_bind()
    documents = sa.table(
        "documents",
        sa.column("id", sa.String(length=36)),
        sa.column("signed_xml", sa.Text()),
        sa.column("generated_xml", sa.Text()),
        sa.column("timbrado", sa.String(length=8)),
    )
    rows = connection.execute(
        sa.select(documents.c.id, documents.c.signed_xml, documents.c.generated_xml)
        .where(
            documents.c.timbrado.is_(None),
            sa.or_(
                documents.c.signed_xml.is_not(None),
                documents.c.generated_xml.is_not(None),
            ),
        )
        .execution_options(yield_per=_BACKFILL_BATCH)
    )
    # Only the (id, timbrado) pairs are kept: the XML is read in batches.
    found = []
    for row in rows:
        timbrado = _timbrado_of(row.signed_xml) or _timbrado_of(row.generated_xml)
        if timbrado is not None:
            found.append({"document_id": row.id, "found_timbrado": timbrado})
    rows.close()
    for start in range(0, len(found), _BACKFILL_BATCH):
        connection.execute(
            documents.update()
            .where(documents.c.id == sa.bindparam("document_id"))
            .values(timbrado=sa.bindparam("found_timbrado")),
            found[start : start + _BACKFILL_BATCH],
        )


def _timbrado_of(xml_text: str | None) -> str | None:
    if not xml_text:
        return None
    match = _TIMBRADO_PATTERN.search(xml_text)
    return match.group(1) if match else None
