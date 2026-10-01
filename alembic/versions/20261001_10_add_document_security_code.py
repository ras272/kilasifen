"""Persist the security code (dCodSeg) of every typed document.

dCodSeg is part of the CDC, so it must be chosen once and reused by every
rebuild and retry of the same document (MT v150 §10.3 and §6.5). Existing
documents are backfilled without inventing a CDC:

- a document that already has a CDC keeps the code inside it (positions
  35-43 of the 44-digit CDC, MT v150 §10.1);
- a typed document not built yet keeps the ``codigo_seguridad`` its caller
  sent, or gets a fresh random code (``secrets``) different from its number;
- a raw-XML document without a CDC carries its own XML and stays NULL.

Revision ID: 20261001_10
Revises: 20261001_09
Create Date: 2026-10-01 12:30:00
"""

import secrets

import sqlalchemy as sa

from alembic import op

revision = "20261001_10"
down_revision = "20261001_09"
branch_labels = None
depends_on = None

_TYPED_CONTRACTS = {"factura_v1", "nota_credito_v1", "nota_debito_v1"}
# Offset of dCodSeg in the CDC: 2+8+1+3+3+7+1+8+1 positions before it.
_CDC_SECURITY_CODE = slice(34, 43)


def upgrade() -> None:
    op.add_column(
        "documents", sa.Column("security_code", sa.String(length=9), nullable=True)
    )

    connection = op.get_bind()
    documents = sa.table(
        "documents",
        sa.column("id", sa.String(length=36)),
        sa.column("cdc", sa.String(length=64)),
        sa.column("payload_snapshot", sa.JSON()),
        sa.column("document_number", sa.Integer()),
        sa.column("security_code", sa.String(length=9)),
    )
    rows = connection.execute(
        sa.select(
            documents.c.id,
            documents.c.cdc,
            documents.c.payload_snapshot,
            documents.c.document_number,
        )
    ).all()
    for document_id, cdc, payload_snapshot, document_number in rows:
        code = _backfilled_code(cdc, payload_snapshot, document_number)
        if code is None:
            continue
        connection.execute(
            documents.update()
            .where(documents.c.id == document_id)
            .values(security_code=code)
        )


def downgrade() -> None:
    op.drop_column("documents", "security_code")


def _backfilled_code(cdc, payload_snapshot, document_number) -> str | None:
    if cdc and len(cdc) == 44:
        return cdc[_CDC_SECURITY_CODE]
    typed_payload = _typed_payload(payload_snapshot)
    if typed_payload is None:
        return None
    number = document_number or _as_int(typed_payload.get("numero"))
    provided = _as_int(typed_payload.get("codigo_seguridad"))
    if provided is not None and 1 <= provided <= 999_999_999 and provided != number:
        return f"{provided:09d}"
    while True:
        value = secrets.randbelow(999_999_999) + 1
        if value != number:
            return f"{value:09d}"


def _typed_payload(payload_snapshot) -> dict | None:
    if not isinstance(payload_snapshot, dict):
        return None
    contract = payload_snapshot.get("typed_contract")
    if not isinstance(contract, dict) or contract.get("contract") not in (
        _TYPED_CONTRACTS
    ):
        return None
    payload = contract.get("payload")
    return payload if isinstance(payload, dict) else None


def _as_int(value) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None
