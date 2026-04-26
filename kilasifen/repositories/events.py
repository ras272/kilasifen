"""Event repository interface."""

from abc import ABC, abstractmethod

from kilasifen.domain.events.models import Event


class EventRepository(ABC):
    """Persistence contract for fiscal events."""

    @abstractmethod
    def save(self, event: Event) -> Event:
        """Persist an event."""

    @abstractmethod
    def get(self, event_id: str) -> Event | None:
        """Load an event by id."""

    @abstractmethod
    def list_for_document(
        self,
        *,
        document_id: str,
        event_type: str | None = None,
        status: str | None = None,
    ) -> list[Event]:
        """List events linked to one document with optional filters."""
