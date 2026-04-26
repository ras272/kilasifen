"""Domain model for inutilized numbering ranges."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class InutilizedNumberRange:
    """One inutilized number range for an emitter and document tuple."""

    id: str
    emitter_id: str
    document_type: str
    establishment: str
    point: str
    numero_desde: int
    numero_hasta: int
    timbrado: str
    event_id: str
    sifen_protocol: str | None
    created_at: datetime
    updated_at: datetime
