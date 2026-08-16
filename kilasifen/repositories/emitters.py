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

    @abstractmethod
    def get_by_external_id(self, external_id: str) -> Emitter | None:
        """Load an emitter by external id."""

    @abstractmethod
    def get_by_tax_id(self, ruc: str, dv: str) -> Emitter | None:
        """Load an emitter by tax id."""

    @abstractmethod
    def list_all(self) -> list[Emitter]:
        """List all emitters."""

    @abstractmethod
    def grant_owner(self, *, consumer_id: str, emitter_id: str) -> None:
        """Assign the emitter to exactly one consumer."""
