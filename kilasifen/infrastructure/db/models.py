"""SQLAlchemy models for Kila SIFEN persistence."""

from __future__ import annotations

from datetime import date, datetime
from uuid import uuid4

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from kilasifen.infrastructure.db.base import Base


def _uuid() -> str:
    return str(uuid4())


class TimestampMixin:
    """Reusable timestamp columns."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class EmitterModel(TimestampMixin, Base):
    __tablename__ = "emitters"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    external_id: Mapped[str | None] = mapped_column(String(128), unique=True)
    ruc: Mapped[str] = mapped_column(String(16), nullable=False)
    dv: Mapped[str] = mapped_column(String(4), nullable=False)
    legal_name: Mapped[str] = mapped_column(String(255), nullable=False)
    tax_environment: Mapped[str] = mapped_column(String(16), nullable=False, default="test")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    csc: Mapped[str | None] = mapped_column(String(255))
    csc_id: Mapped[str | None] = mapped_column(String(16))

    certificates: Mapped[list["CertificateModel"]] = relationship(back_populates="emitter")
    stampings: Mapped[list["StampingModel"]] = relationship(back_populates="emitter")
    documents: Mapped[list["DocumentModel"]] = relationship(back_populates="emitter")
    jobs: Mapped[list["JobModel"]] = relationship(back_populates="emitter")
    events: Mapped[list["EventModel"]] = relationship(back_populates="emitter")
    webhook_endpoints: Mapped[list["WebhookEndpointModel"]] = relationship(back_populates="emitter")
    api_keys: Mapped[list["ApiKeyModel"]] = relationship(back_populates="emitter")

    __table_args__ = (UniqueConstraint("ruc", "dv", name="uq_emitters_ruc_dv"),)


class ApiKeyModel(TimestampMixin, Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    emitter_id: Mapped[str | None] = mapped_column(ForeignKey("emitters.id"))
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(32), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")

    emitter: Mapped[EmitterModel | None] = relationship(back_populates="api_keys")


class CertificateModel(TimestampMixin, Base):
    __tablename__ = "certificates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    emitter_id: Mapped[str] = mapped_column(ForeignKey("emitters.id"), nullable=False)
    logical_name: Mapped[str] = mapped_column(String(255), nullable=False)
    encrypted_p12: Mapped[str] = mapped_column(Text, nullable=False)
    encrypted_password: Mapped[str] = mapped_column(Text, nullable=False)
    fingerprint: Mapped[str | None] = mapped_column(String(255))
    serial_number: Mapped[str | None] = mapped_column(String(255))
    subject_summary: Mapped[str | None] = mapped_column(String(255))
    detected_ruc: Mapped[str | None] = mapped_column(String(32))
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="uploaded")

    emitter: Mapped[EmitterModel] = relationship(back_populates="certificates")


class StampingModel(TimestampMixin, Base):
    __tablename__ = "stampings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    emitter_id: Mapped[str] = mapped_column(ForeignKey("emitters.id"), nullable=False)
    number: Mapped[str] = mapped_column(String(32), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")

    emitter: Mapped[EmitterModel] = relationship(back_populates="stampings")


class DocumentModel(TimestampMixin, Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    emitter_id: Mapped[str] = mapped_column(ForeignKey("emitters.id"), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(128))
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    document_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_snapshot: Mapped[dict | None] = mapped_column(JSON)
    generated_xml: Mapped[str | None] = mapped_column(Text)
    signed_xml: Mapped[str | None] = mapped_column(Text)
    cdc: Mapped[str | None] = mapped_column(String(64))
    internal_status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    sifen_status: Mapped[str | None] = mapped_column(String(32))
    sifen_result_code: Mapped[str | None] = mapped_column(String(16))
    sifen_result_message: Mapped[str | None] = mapped_column(Text)

    emitter: Mapped[EmitterModel] = relationship(back_populates="documents")
    events: Mapped[list["EventModel"]] = relationship(back_populates="document")

    __table_args__ = (
        UniqueConstraint("emitter_id", "external_id", name="uq_documents_emitter_external_id"),
        UniqueConstraint("emitter_id", "idempotency_key", name="uq_documents_emitter_idempotency_key"),
    )


class JobModel(TimestampMixin, Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    emitter_id: Mapped[str | None] = mapped_column(ForeignKey("emitters.id"))
    related_entity_type: Mapped[str | None] = mapped_column(String(64))
    related_entity_id: Mapped[str | None] = mapped_column(String(36))
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_snapshot: Mapped[dict | None] = mapped_column(JSON)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    worker_correlation_id: Mapped[str | None] = mapped_column(String(64))

    emitter: Mapped[EmitterModel | None] = relationship(back_populates="jobs")


class EventModel(TimestampMixin, Base):
    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    emitter_id: Mapped[str] = mapped_column(ForeignKey("emitters.id"), nullable=False)
    document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id"))
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    input_payload: Mapped[dict | None] = mapped_column(JSON)
    generated_xml: Mapped[str | None] = mapped_column(Text)
    signed_xml: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    sifen_result_code: Mapped[str | None] = mapped_column(String(16))
    sifen_result_message: Mapped[str | None] = mapped_column(Text)

    emitter: Mapped[EmitterModel] = relationship(back_populates="events")
    document: Mapped[DocumentModel | None] = relationship(back_populates="events")


class WebhookEndpointModel(TimestampMixin, Base):
    __tablename__ = "webhook_endpoints"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    emitter_id: Mapped[str | None] = mapped_column(ForeignKey("emitters.id"))
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    secret_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    event_subscriptions: Mapped[list[str] | None] = mapped_column(JSON)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    retry_policy: Mapped[dict | None] = mapped_column(JSON)

    emitter: Mapped[EmitterModel | None] = relationship(back_populates="webhook_endpoints")
    deliveries: Mapped[list["WebhookDeliveryModel"]] = relationship(back_populates="webhook_endpoint")


class WebhookDeliveryModel(TimestampMixin, Base):
    __tablename__ = "webhook_deliveries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    webhook_endpoint_id: Mapped[str] = mapped_column(ForeignKey("webhook_endpoints.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_snapshot: Mapped[dict | None] = mapped_column(JSON)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    request_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    response_code: Mapped[int | None] = mapped_column(Integer)
    response_body_snapshot: Mapped[str | None] = mapped_column(Text)
    final_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")

    webhook_endpoint: Mapped[WebhookEndpointModel] = relationship(back_populates="deliveries")
