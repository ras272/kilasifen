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
