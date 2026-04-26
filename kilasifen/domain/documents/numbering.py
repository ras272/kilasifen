"""Document numbering domain models."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class DocumentNumberingSequence:
    """Persistent sequence state for one numbering tuple."""

    id: str
    emitter_id: str
    establishment: str
    point: str
    document_type: str
    last_number: int
    updated_at: datetime

