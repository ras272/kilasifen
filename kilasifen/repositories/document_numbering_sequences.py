"""Document numbering sequence repository interface."""

from abc import ABC, abstractmethod

from kilasifen.domain.documents.numbering import DocumentNumberingSequence


class DocumentNumberingSequenceRepository(ABC):
    """Persistence contract for document numbering sequences."""

    @abstractmethod
    def get_current(
        self,
        *,
        emitter_id: str,
        establishment: str,
        point: str,
        document_type: str,
    ) -> DocumentNumberingSequence | None:
        """Load current sequence state for one numbering tuple."""

    @abstractmethod
    def reserve_next_number(
        self,
        *,
        emitter_id: str,
        establishment: str,
        point: str,
        document_type: str,
    ) -> int:
        """Atomically reserve and return the next sequence number."""
