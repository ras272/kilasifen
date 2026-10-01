"""Emitter operational health service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from kilasifen.domain.common.errors import NotFoundError
from kilasifen.repositories.certificates import CertificateRepository
from kilasifen.repositories.documents import DocumentRepository
from kilasifen.repositories.emitters import EmitterRepository
from kilasifen.repositories.jobs import JobRepository
from kilasifen.repositories.stampings import StampingRepository


@dataclass(slots=True)
class EmitterHealthSnapshot:
    """Operational snapshot for one emitter."""

    emitter_id: str
    emitter_status: str
    has_active_certificate: bool
    certificate_valid_until: datetime | None
    has_active_stamping: bool
    stamping_number: str | None
    stamping_valid_on: date
    queue_queued_count: int
    queue_retry_count: int
    queue_failed_count: int
    last_document_id: str | None
    last_document_status: str | None
    checked_at: datetime


class EmitterHealthService:
    """Compute operational health indicators for one emitter."""

    def __init__(
        self,
        *,
        emitter_repository: EmitterRepository,
        certificate_repository: CertificateRepository,
        stamping_repository: StampingRepository,
        document_repository: DocumentRepository,
        job_repository: JobRepository,
    ):
        self.emitter_repository = emitter_repository
        self.certificate_repository = certificate_repository
        self.stamping_repository = stamping_repository
        self.document_repository = document_repository
        self.job_repository = job_repository

    def get_health(self, *, emitter_id: str, on_date: date | None = None) -> EmitterHealthSnapshot:
        emitter = self.emitter_repository.get(emitter_id)
        if emitter is None:
            raise NotFoundError("emitters.not_found")

        target_date = on_date or date.today()
        active_certificate = self.certificate_repository.get_active_for_emitter(emitter_id)
        active_stamping = self.stamping_repository.get_active_for_emitter(
            emitter_id,
            on_date=target_date,
        )
        recent_jobs = self.job_repository.list_recent(limit=200, emitter_id=emitter_id)
        recent_documents = self.document_repository.list_recent(limit=1, emitter_id=emitter_id)

        queue_queued_count = sum(1 for job in recent_jobs if job.status == "queued")
        queue_retry_count = sum(1 for job in recent_jobs if job.status == "retry_scheduled")
        queue_failed_count = sum(1 for job in recent_jobs if job.status == "failed")
        last_document = recent_documents[0] if recent_documents else None
        return EmitterHealthSnapshot(
            emitter_id=emitter.id,
            emitter_status=emitter.status,
            has_active_certificate=active_certificate is not None,
            certificate_valid_until=active_certificate.valid_until if active_certificate else None,
            has_active_stamping=active_stamping is not None,
            stamping_number=active_stamping.number if active_stamping else None,
            stamping_valid_on=target_date,
            queue_queued_count=queue_queued_count,
            queue_retry_count=queue_retry_count,
            queue_failed_count=queue_failed_count,
            last_document_id=last_document.id if last_document else None,
            last_document_status=last_document.internal_status if last_document else None,
            checked_at=datetime.now(timezone.utc),
        )
