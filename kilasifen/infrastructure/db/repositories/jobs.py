"""SQLAlchemy implementation of the job repository."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from kilasifen.domain.jobs.models import Job
from kilasifen.infrastructure.db.models import JobModel
from kilasifen.repositories.jobs import JobRepository


class SqlAlchemyJobRepository(JobRepository):
    """Persist jobs with SQLAlchemy."""

    def __init__(self, session: Session):
        self.session = session

    def save(self, job: Job) -> Job:
        existing = self.session.get(JobModel, job.id)
        if existing is None:
            model = JobModel(
                id=job.id,
                emitter_id=job.emitter_id,
                related_entity_type=job.related_entity_type,
                related_entity_id=job.related_entity_id,
                job_type=job.job_type,
                status=job.status,
                attempts=job.attempts,
                error_snapshot=job.error_snapshot,
                scheduled_at=job.scheduled_at,
                started_at=job.started_at,
                finished_at=job.finished_at,
                worker_correlation_id=job.worker_correlation_id,
                created_at=job.created_at,
                updated_at=job.updated_at,
            )
            self.session.add(model)
        else:
            existing.related_entity_type = job.related_entity_type
            existing.related_entity_id = job.related_entity_id
            existing.job_type = job.job_type
            existing.status = job.status
            existing.attempts = job.attempts
            existing.error_snapshot = job.error_snapshot
            existing.scheduled_at = job.scheduled_at
            existing.started_at = job.started_at
            existing.finished_at = job.finished_at
            existing.worker_correlation_id = job.worker_correlation_id
            existing.updated_at = job.updated_at
        self.session.flush()
        return job

    def get(self, job_id: str) -> Job | None:
        model = self.session.get(JobModel, job_id)
        if model is None:
            return None
        return _to_domain(model)

    def get_for_entity(self, entity_type: str, entity_id: str) -> Job | None:
        statement = (
            select(JobModel)
            .where(
                JobModel.related_entity_type == entity_type,
                JobModel.related_entity_id == entity_id,
            )
            .order_by(JobModel.created_at.desc())
        )
        model = self.session.scalars(statement).first()
        if model is None:
            return None
        return _to_domain(model)


def _to_domain(model: JobModel) -> Job:
    return Job(
        id=model.id,
        emitter_id=model.emitter_id,
        related_entity_type=model.related_entity_type,
        related_entity_id=model.related_entity_id,
        job_type=model.job_type,
        status=model.status,
        attempts=model.attempts,
        error_snapshot=model.error_snapshot,
        scheduled_at=model.scheduled_at,
        started_at=model.started_at,
        finished_at=model.finished_at,
        worker_correlation_id=model.worker_correlation_id,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )
