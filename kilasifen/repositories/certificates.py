"""Certificate repository interface."""

from abc import ABC, abstractmethod

from kilasifen.domain.certificates.models import Certificate


class CertificateRepository(ABC):
    """Persistence contract for certificates."""

    @abstractmethod
    def save(self, certificate: Certificate) -> Certificate:
        """Persist a certificate."""

    @abstractmethod
    def list_for_emitter(self, emitter_id: str) -> list[Certificate]:
        """List certificates for one emitter."""

    @abstractmethod
    def get_active_for_emitter(self, emitter_id: str) -> Certificate | None:
        """Return the active certificate for one emitter."""
