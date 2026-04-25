"""Stamping repository interface."""

from abc import ABC, abstractmethod
from datetime import date

from kilasifen.domain.stampings.models import Stamping


class StampingRepository(ABC):
    """Persistence contract for stampings."""

    @abstractmethod
    def save(self, stamping: Stamping) -> Stamping:
        """Persist a stamping."""

    @abstractmethod
    def list_for_emitter(self, emitter_id: str) -> list[Stamping]:
        """List stampings for one emitter."""

    @abstractmethod
    def get_active_for_emitter(self, emitter_id: str, on_date: date) -> Stamping | None:
        """Return the active stamping for one emitter."""

    @abstractmethod
    def get(self, stamping_id: str) -> Stamping | None:
        """Load a stamping by id."""

    @abstractmethod
    def deactivate_others(self, emitter_id: str, active_stamping_id: str) -> None:
        """Deactivate all other stampings for the emitter."""
