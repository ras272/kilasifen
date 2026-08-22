"""SQLAlchemy implementation of the durable job outbox."""

from datetime import datetime
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import and_, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from kilasifen.domain.jobs.outbox import JobOutboxMessage
from kilasifen.infrastructure.db.models import JobOutboxModel
from kilasifen.repositories.job_outbox import JobOutboxRepository


class SqlAlchemyJobOutboxRepository(JobOutboxRepository):
    """Persist and lease queue publications without leaving the database."""

    def __init__(self, session: Session):
        self.session = session

    def stage(
        self,
        *,
        job_id: str,
        queue_name: str,
        correlation_id: str | None,
    ) -> JobOutboxMessage:
        existing = self._model_for_job(job_id)
        if existing is None:
            now = _now()
            existing = JobOutboxModel(
                id=str(uuid4()),
                job_id=job_id,
                queue_name=queue_name,
                correlation_id=correlation_id,
                status="pending",
                attempts=0,
                available_at=now,
                locked_until=None,
                locked_by=None,
                published_at=None,
                last_error=None,
                created_at=now,
                updated_at=now,
            )
            self.session.add(existing)
        elif existing.status == "published":
            existing.queue_name = queue_name
            existing.correlation_id = correlation_id
            existing.status = "pending"
            existing.attempts = 0
            existing.available_at = _now()
            existing.locked_until = None
            existing.locked_by = None
            existing.published_at = None
            existing.last_error = None
            existing.updated_at = _now()
        self.session.flush()
        return _to_domain(existing)

    def claim_batch(
        self,
        *,
        worker_id: str,
        now: datetime,
        locked_until: datetime,
        limit: int,
    ) -> list[JobOutboxMessage]:
        dispatchable = _dispatchable(now)
        candidate_ids = list(
            self.session.scalars(
                select(JobOutboxModel.id)
                .where(dispatchable)
                .order_by(JobOutboxModel.available_at, JobOutboxModel.created_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        claimed_ids: list[str] = []
        for message_id in candidate_ids:
            result = cast(
                CursorResult[Any],
                self.session.execute(
                    update(JobOutboxModel)
                    .where(JobOutboxModel.id == message_id, _dispatchable(now))
                    .values(
                        status="publishing",
                        attempts=JobOutboxModel.attempts + 1,
                        locked_until=locked_until,
                        locked_by=worker_id,
                        updated_at=now,
                    )
                ),
            )
            if result.rowcount == 1:
                claimed_ids.append(message_id)
        self.session.flush()
        if not claimed_ids:
            return []
        models = self.session.scalars(
            select(JobOutboxModel)
            .where(JobOutboxModel.id.in_(claimed_ids))
            .order_by(JobOutboxModel.available_at, JobOutboxModel.created_at)
        )
        return [_to_domain(model) for model in models]

    def mark_published(
        self,
        *,
        message_id: str,
        worker_id: str,
        published_at: datetime,
    ) -> bool:
        result = cast(
            CursorResult[Any],
            self.session.execute(
                update(JobOutboxModel)
                .where(
                    JobOutboxModel.id == message_id,
                    JobOutboxModel.status == "publishing",
                    JobOutboxModel.locked_by == worker_id,
                )
                .values(
                    status="published",
                    locked_until=None,
                    locked_by=None,
                    published_at=published_at,
                    last_error=None,
                    updated_at=published_at,
                )
            ),
        )
        self.session.flush()
        return result.rowcount == 1

    def mark_failed(
        self,
        *,
        message_id: str,
        worker_id: str,
        available_at: datetime,
        last_error: str,
        updated_at: datetime,
    ) -> bool:
        result = cast(
            CursorResult[Any],
            self.session.execute(
                update(JobOutboxModel)
                .where(
                    JobOutboxModel.id == message_id,
                    JobOutboxModel.status == "publishing",
                    JobOutboxModel.locked_by == worker_id,
                )
                .values(
                    status="pending",
                    available_at=available_at,
                    locked_until=None,
                    locked_by=None,
                    last_error=last_error,
                    updated_at=updated_at,
                )
            ),
        )
        self.session.flush()
        return result.rowcount == 1

    def get(self, message_id: str) -> JobOutboxMessage | None:
        model = self.session.get(JobOutboxModel, message_id)
        return _to_domain(model) if model is not None else None

    def get_for_job(self, job_id: str) -> JobOutboxMessage | None:
        model = self._model_for_job(job_id)
        return _to_domain(model) if model is not None else None

    def _model_for_job(self, job_id: str) -> JobOutboxModel | None:
        return self.session.scalar(
            select(JobOutboxModel).where(JobOutboxModel.job_id == job_id)
        )


def _dispatchable(now: datetime):
    return or_(
        and_(
            JobOutboxModel.status == "pending",
            JobOutboxModel.available_at <= now,
        ),
        and_(
            JobOutboxModel.status == "publishing",
            JobOutboxModel.locked_until <= now,
        ),
    )


def _to_domain(model: JobOutboxModel) -> JobOutboxMessage:
    return JobOutboxMessage(
        id=model.id,
        job_id=model.job_id,
        queue_name=model.queue_name,
        correlation_id=model.correlation_id,
        status=model.status,
        attempts=model.attempts,
        available_at=model.available_at,
        locked_until=model.locked_until,
        locked_by=model.locked_by,
        published_at=model.published_at,
        last_error=model.last_error,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _now() -> datetime:
    from datetime import UTC

    return datetime.now(UTC)
