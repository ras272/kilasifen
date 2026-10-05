"""Emitter domain models."""

from dataclasses import dataclass
from datetime import datetime

from kilasifen.domain.emitters.fiscal_profile import EmitterFiscalProfile


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
    # None until the emitter registers the data of its RUC (MT v150 D103-D132).
    fiscal_profile: EmitterFiscalProfile | None = None


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
    fiscal_profile: EmitterFiscalProfile | None = None
