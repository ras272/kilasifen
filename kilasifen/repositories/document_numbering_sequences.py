"""Document numbering sequence repository interface."""

from abc import ABC, abstractmethod


class DocumentNumberingSequenceRepository(ABC):
    """Persistence contract for document numbering sequences."""

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

