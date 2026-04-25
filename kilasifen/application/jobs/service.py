"""Job application service layer."""

from datetime import UTC, datetime
from uuid import uuid4

from kilasifen.domain.common.errors import NotFoundError
from kilasifen.domain.jobs.models import Job
from kilasifen.repositories.jobs import JobRepository


class JobService:
    """Use cases for jobs."""

    def __init__(self, repository: JobRepository):
        self.repository = repository

    def create_job(
        self,
        *,
        emitter_id: str | None,
        related_entity_type: str,
        related_entity_id: str,
        job_type: str,
    ) -> Job:
        timestamp = _now()
        job = Job(
            id=str(uuid4()),
            emitter_id=emitter_id,
            related_entity_type=related_entity_type,
            related_entity_id=related_entity_id,
            job_type=job_type,
            status="queued",
            attempts=0,
            error_snapshot=None,
            scheduled_at=timestamp,
            started_at=None,
            finished_at=None,
            worker_correlation_id=None,
            created_at=timestamp,
            updated_at=timestamp,
        )
        return self.repository.save(job)

    def get_job(self, job_id: str) -> Job:
        job = self.repository.get(job_id)
        if job is None:
            raise NotFoundError("jobs.not_found")
        return job

    def get_for_entity(self, entity_type: str, entity_id: str) -> Job | None:
        return self.repository.get_for_entity(entity_type, entity_id)


def _now() -> datetime:
    return datetime.now(UTC)
