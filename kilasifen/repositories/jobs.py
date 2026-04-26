"""Job repository interface."""

from abc import ABC, abstractmethod

from kilasifen.domain.jobs.models import Job


class JobRepository(ABC):
    """Persistence contract for jobs."""

    @abstractmethod
    def save(self, job: Job) -> Job:
        """Persist a job."""

    @abstractmethod
    def get(self, job_id: str) -> Job | None:
        """Load a job by id."""

    @abstractmethod
    def get_for_entity(self, entity_type: str, entity_id: str) -> Job | None:
        """Load the latest job for a related entity."""

    @abstractmethod
    def list_recent(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        emitter_id: str | None = None,
        status: str | None = None,
        job_type: str | None = None,
        related_entity_type: str | None = None,
    ) -> list[Job]:
        """List recent jobs with optional filters."""
