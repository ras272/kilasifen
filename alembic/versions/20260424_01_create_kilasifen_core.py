"""create kilasifen core schema

Revision ID: 20260424_01
Revises:
Create Date: 2026-04-24 21:20:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260424_01"
down_revision = None
branch_labels = None
depends_on = None


def _timestamp_column(name: str) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )


def upgrade() -> None:
    op.create_table(
        "emitters",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("external_id", sa.String(length=128), nullable=True),
        sa.Column("ruc", sa.String(length=16), nullable=False),
        sa.Column("dv", sa.String(length=4), nullable=False),
        sa.Column("legal_name", sa.String(length=255), nullable=False),
        sa.Column("tax_environment", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("csc", sa.String(length=255), nullable=True),
        sa.Column("csc_id", sa.String(length=16), nullable=True),
        _timestamp_column("created_at"),
        _timestamp_column("updated_at"),
        sa.UniqueConstraint("external_id", name="uq_emitters_external_id"),
        sa.UniqueConstraint("ruc", "dv", name="uq_emitters_ruc_dv"),
    )

    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("emitter_id", sa.String(length=36), nullable=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("key_prefix", sa.String(length=32), nullable=False),
        sa.Column("key_hash", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        _timestamp_column("created_at"),
        _timestamp_column("updated_at"),
        sa.ForeignKeyConstraint(["emitter_id"], ["emitters.id"], name="fk_api_keys_emitter_id_emitters"),
        sa.UniqueConstraint("key_hash", name="uq_api_keys_key_hash"),
    )

    op.create_table(
        "certificates",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("emitter_id", sa.String(length=36), nullable=False),
        sa.Column("logical_name", sa.String(length=255), nullable=False),
        sa.Column("encrypted_p12", sa.Text(), nullable=False),
        sa.Column("encrypted_password", sa.Text(), nullable=False),
        sa.Column("fingerprint", sa.String(length=255), nullable=True),
        sa.Column("serial_number", sa.String(length=255), nullable=True),
        sa.Column("subject_summary", sa.String(length=255), nullable=True),
        sa.Column("detected_ruc", sa.String(length=32), nullable=True),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(length=32), nullable=False),
        _timestamp_column("created_at"),
        _timestamp_column("updated_at"),
        sa.ForeignKeyConstraint(
            ["emitter_id"],
            ["emitters.id"],
            name="fk_certificates_emitter_id_emitters",
        ),
    )

    op.create_table(
        "stampings",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("emitter_id", sa.String(length=36), nullable=False),
        sa.Column("number", sa.String(length=32), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(length=32), nullable=False),
        _timestamp_column("created_at"),
        _timestamp_column("updated_at"),
        sa.ForeignKeyConstraint(["emitter_id"], ["emitters.id"], name="fk_stampings_emitter_id_emitters"),
    )

    op.create_table(
        "documents",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("emitter_id", sa.String(length=36), nullable=False),
        sa.Column("external_id", sa.String(length=128), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("document_type", sa.String(length=64), nullable=False),
        sa.Column("payload_snapshot", sa.JSON(), nullable=True),
        sa.Column("generated_xml", sa.Text(), nullable=True),
        sa.Column("signed_xml", sa.Text(), nullable=True),
        sa.Column("cdc", sa.String(length=64), nullable=True),
        sa.Column("internal_status", sa.String(length=32), nullable=False),
        sa.Column("sifen_status", sa.String(length=32), nullable=True),
        sa.Column("sifen_result_code", sa.String(length=16), nullable=True),
        sa.Column("sifen_result_message", sa.Text(), nullable=True),
        _timestamp_column("created_at"),
        _timestamp_column("updated_at"),
        sa.ForeignKeyConstraint(["emitter_id"], ["emitters.id"], name="fk_documents_emitter_id_emitters"),
        sa.UniqueConstraint("emitter_id", "external_id", name="uq_documents_emitter_external_id"),
        sa.UniqueConstraint("emitter_id", "idempotency_key", name="uq_documents_emitter_idempotency_key"),
    )

    op.create_table(
        "jobs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("emitter_id", sa.String(length=36), nullable=True),
        sa.Column("related_entity_type", sa.String(length=64), nullable=True),
        sa.Column("related_entity_id", sa.String(length=36), nullable=True),
        sa.Column("job_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_snapshot", sa.JSON(), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("worker_correlation_id", sa.String(length=64), nullable=True),
        _timestamp_column("created_at"),
        _timestamp_column("updated_at"),
        sa.ForeignKeyConstraint(["emitter_id"], ["emitters.id"], name="fk_jobs_emitter_id_emitters"),
    )

    op.create_table(
        "events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("emitter_id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("input_payload", sa.JSON(), nullable=True),
        sa.Column("generated_xml", sa.Text(), nullable=True),
        sa.Column("signed_xml", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("sifen_result_code", sa.String(length=16), nullable=True),
        sa.Column("sifen_result_message", sa.Text(), nullable=True),
        _timestamp_column("created_at"),
        _timestamp_column("updated_at"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], name="fk_events_document_id_documents"),
        sa.ForeignKeyConstraint(["emitter_id"], ["emitters.id"], name="fk_events_emitter_id_emitters"),
    )

    op.create_table(
        "webhook_endpoints",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("emitter_id", sa.String(length=36), nullable=True),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("secret_encrypted", sa.Text(), nullable=False),
        sa.Column("event_subscriptions", sa.JSON(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("retry_policy", sa.JSON(), nullable=True),
        _timestamp_column("created_at"),
        _timestamp_column("updated_at"),
        sa.ForeignKeyConstraint(
            ["emitter_id"],
            ["emitters.id"],
            name="fk_webhook_endpoints_emitter_id_emitters",
        ),
    )

    op.create_table(
        "webhook_deliveries",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("webhook_endpoint_id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payload_snapshot", sa.JSON(), nullable=True),
        sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("request_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("response_code", sa.Integer(), nullable=True),
        sa.Column("response_body_snapshot", sa.Text(), nullable=True),
        sa.Column("final_status", sa.String(length=32), nullable=False),
        _timestamp_column("created_at"),
        _timestamp_column("updated_at"),
        sa.ForeignKeyConstraint(
            ["webhook_endpoint_id"],
            ["webhook_endpoints.id"],
            name="fk_webhook_deliveries_webhook_endpoint_id_webhook_endpoints",
        ),
    )


def downgrade() -> None:
    op.drop_table("webhook_deliveries")
    op.drop_table("webhook_endpoints")
    op.drop_table("events")
    op.drop_table("jobs")
    op.drop_table("documents")
    op.drop_table("stampings")
    op.drop_table("certificates")
    op.drop_table("api_keys")
    op.drop_table("emitters")
