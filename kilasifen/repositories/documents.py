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
    def get_for_update(self, document_id: str) -> Document | None:
        """Lock a document row and load its committed state."""

    @abstractmethod
    def get_by_idempotency_key(self, emitter_id: str, idempotency_key: str) -> Document | None:
        """Load a document by emitter and idempotency key."""

    @abstractmethod
    def get_by_external_id(self, emitter_id: str, external_id: str) -> Document | None:
        """Load a document by emitter and external id."""

    @abstractmethod
    def get_by_cdc(self, emitter_id: str, cdc: str) -> Document | None:
        """Load a document by emitter and CDC."""

    @abstractmethod
    def list_by_associated_cdc(self, *, emitter_id: str, associated_cdc: str) -> list[Document]:
        """List documents that reference the given CDC in typed payloads."""

    @abstractmethod
    def list_in_number_range(
        self,
        *,
        emitter_id: str,
        document_type: str,
        establishment: str,
        point: str,
        number_from: int,
        number_to: int,
        timbrado: str,
    ) -> list[Document]:
        """List the documents numbered inside one range of one timbrado.

        A document whose timbrado is not known yet (never prepared) counts
        for every timbrado.
        """

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
