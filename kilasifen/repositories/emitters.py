"""Emitter repository interface."""

from abc import ABC, abstractmethod
from datetime import datetime

from kilasifen.domain.emitters.fiscal_profile import EmitterFiscalProfile
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
    def get_summary(self, emitter_id: str) -> EmitterSummary | None:
        """Load an emitter, fiscal profile included, without its secrets."""

    @abstractmethod
    def get_status(self, emitter_id: str) -> str | None:
        """Return an emitter status without locking the row or loading secrets."""

    @abstractmethod
    def get_status_for_update(self, emitter_id: str) -> str | None:
        """Lock an emitter row and return its status without loading secrets.

        The wait for the lock is bounded: when it runs out the implementation
        raises ``ServiceUnavailableError("emitters.lock_timeout")``.
        """

    @abstractmethod
    def lock_row(self, emitter_id: str) -> None:
        """Lock an emitter row whatever its status, waiting as long as needed.

        For writers that must not give up and only need the lock to follow
        the order every writer shares (emitter, then document or event, then
        job), such as a worker recording an answer SIFEN already gave. The
        lock is only ever held by short transactions, so the wait is short.
        """

    @abstractmethod
    def update_metadata(
        self,
        emitter_id: str,
        *,
        legal_name: str | None,
        tax_environment: str | None,
        updated_at: datetime,
        fiscal_profile: EmitterFiscalProfile | None = None,
    ) -> EmitterSummary | None:
        """Update only non-secret emitter columns; ``None`` keeps a value."""

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
