"""Document repository interface."""

from abc import ABC, abstractmethod

from kilasifen.domain.documents.models import Document


class DocumentRepository(ABC):
    """Persistence contract for documents."""

    @abstractmethod
    def save(self, document: Document) -> Document:
        """Persist a document."""

    @abstractmethod
    def get(self, document_id: str) -> Document | None:
        """Load a document by id."""

    @abstractmethod
    def get_by_idempotency_key(self, emitter_id: str, idempotency_key: str) -> Document | None:
        """Load a document by emitter and idempotency key."""

    @abstractmethod
    def get_by_external_id(self, emitter_id: str, external_id: str) -> Document | None:
        """Load a document by emitter and external id."""

    @abstractmethod
    def list_recent(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        emitter_id: str | None = None,
        internal_status: str | None = None,
        document_type: str | None = None,
        external_id: str | None = None,
        cdc: str | None = None,
    ) -> list[Document]:
        """List recent documents with optional filters."""
