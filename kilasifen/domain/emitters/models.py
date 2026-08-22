"""Emitter domain models."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class Emitter:
    """A fiscal emitter managed by the platform."""

    id: str
    external_id: str | None
    ruc: str
    dv: str
    legal_name: str
    tax_environment: str
    status: str
    csc: str | None
    csc_id: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class EmitterSummary:
    """Secret-free emitter projection returned by mutation operations."""

    id: str
    external_id: str | None
    ruc: str
    dv: str
    legal_name: str
    tax_environment: str
    status: str
    csc_configured: bool
    csc_id: str | None
    created_at: datetime
    updated_at: datetime
