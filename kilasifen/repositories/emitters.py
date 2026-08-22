"""Emitter repository interface."""

from abc import ABC, abstractmethod
from datetime import datetime

from kilasifen.domain.emitters.models import Emitter, EmitterSummary


class EmitterRepository(ABC):
    """Persistence contract for emitters."""

    @abstractmethod
    def save(self, emitter: Emitter) -> Emitter:
        """Persist an emitter."""

    @abstractmethod
    def get(self, emitter_id: str) -> Emitter | None:
        """Load an emitter by id."""

    @abstractmethod
    def get_status_for_update(self, emitter_id: str) -> str | None:
        """Lock an emitter row and return its status without loading secrets."""

    @abstractmethod
    def update_metadata(
        self,
        emitter_id: str,
        *,
        legal_name: str | None,
        tax_environment: str | None,
        updated_at: datetime,
    ) -> EmitterSummary | None:
        """Update only non-secret emitter columns."""

    @abstractmethod
    def update_secret(
        self,
        emitter_id: str,
        *,
        csc: str | None,
        csc_id: str | None,
        updated_at: datetime,
    ) -> EmitterSummary | None:
        """Update secret columns while the caller holds the emitter row lock."""

    @abstractmethod
    def deactivate(
        self,
        emitter_id: str,
        *,
        updated_at: datetime,
    ) -> EmitterSummary | None:
        """Deactivate an emitter without loading or writing its secrets."""

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
