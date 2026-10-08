"""Index the lookups that every request or document read makes.

Without these, PostgreSQL scans the whole table: the job of each listed
document (one lookup per document), the credential of every authenticated
request, an emitter's documents and jobs newest first, a document by CDC and
the events of a document. With 300 000 jobs a page of 50 documents took
1.5 s in job lookups alone (SQLite, 2026-10-08) and 0.7 ms with the index.

Revision ID: 20261008_16
Revises: 20261001_15
Create Date: 2026-10-08 12:00:00
"""

from alembic import op

revision = "20261008_16"
down_revision = "20261001_15"
branch_labels = None
depends_on = None

_INDEXES = (
    ("ix_api_keys_key_prefix", "api_keys", ["key_prefix"]),
    ("ix_documents_emitter_created", "documents", ["emitter_id", "created_at"]),
    ("ix_documents_emitter_cdc", "documents", ["emitter_id", "cdc"]),
    (
        "ix_jobs_related_entity",
        "jobs",
        ["related_entity_type", "related_entity_id", "created_at"],
    ),
    ("ix_jobs_emitter_created", "jobs", ["emitter_id", "created_at"]),
    ("ix_events_document_created", "events", ["document_id", "created_at"]),
)


def upgrade() -> None:
    for name, table, columns in _INDEXES:
        op.create_index(name, table, columns)


def downgrade() -> None:
    for name, table, _ in reversed(_INDEXES):
        op.drop_index(name, table_name=table)
