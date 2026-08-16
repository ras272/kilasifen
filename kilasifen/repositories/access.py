"""Persistence contract for consumer access administration."""

from abc import ABC, abstractmethod

from kilasifen.domain.access.models import ApiCredential, Consumer


class AccessRepository(ABC):
    @abstractmethod
    def create_consumer(self, *, name: str) -> Consumer:
        """Create a consumer with a unique name."""

    @abstractmethod
    def get_consumer(self, consumer_id: str) -> Consumer | None:
        """Load a consumer."""

    @abstractmethod
    def get_consumer_by_name(self, name: str) -> Consumer | None:
        """Load a consumer by its unique operational name."""

    @abstractmethod
    def issue_credential(
        self,
        *,
        consumer_id: str,
        name: str,
        raw_key: str,
        scopes: tuple[str, ...],
    ) -> ApiCredential:
        """Persist only a one-way representation of a new credential."""

    @abstractmethod
    def revoke_credential(
        self, *, consumer_id: str, credential_id: str
    ) -> ApiCredential | None:
        """Deactivate one credential owned by the consumer."""
