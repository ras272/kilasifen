"""Application service for document numbering."""

from kilasifen.repositories.document_numbering_sequences import (
    DocumentNumberingSequenceRepository,
)


class DocumentNumberingService:
    """Use cases for server-side document numbering.

    Reserved numbers are never released, even if document emission fails later.
    This is intentional for fiscal traceability and aligns with the required
    flow where gaps must be handled via explicit inutilizacion events.
    """

    def __init__(self, repository: DocumentNumberingSequenceRepository):
        self.repository = repository

    def reserve_next_number(
        self,
        *,
        emitter_id: str,
        establishment: str,
        point: str,
        document_type: str,
    ) -> int:
        return self.repository.reserve_next_number(
            emitter_id=emitter_id,
            establishment=establishment,
            point=point,
            document_type=document_type,
        )

