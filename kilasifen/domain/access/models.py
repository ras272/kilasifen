"""Consumer and API credential domain records."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Consumer:
    id: str
    name: str
    status: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ApiCredential:
    id: str
    consumer_id: str
    name: str
    key_prefix: str
    scopes: tuple[str, ...]
    status: str
    created_at: datetime
    updated_at: datetime
