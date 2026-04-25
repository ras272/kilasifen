"""Emitter repository interface."""

from abc import ABC, abstractmethod

from kilasifen.domain.emitters.models import Emitter


class EmitterRepository(ABC):
    """Persistence contract for emitters."""

    @abstractmethod
    def save(self, emitter: Emitter) -> Emitter:
        """Persist an emitter."""

    @abstractmethod
    def get(self, emitter_id: str) -> Emitter | None:
        """Load an emitter by id."""
