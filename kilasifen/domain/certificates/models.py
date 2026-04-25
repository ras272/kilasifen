"""Certificate domain models and invariants."""

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from kilasifen.domain.common.errors import DomainInvariantError


@dataclass(slots=True)
class Certificate:
    """A certificate stored for one emitter."""

    id: str
    emitter_id: str
    logical_name: str
    encrypted_p12: str
    encrypted_password: str
    fingerprint: str | None
    serial_number: str | None
    subject_summary: str | None
    detected_ruc: str | None
    valid_from: datetime | None
    valid_until: datetime | None
    is_active: bool
    status: str
    created_at: datetime
    updated_at: datetime


def ensure_single_active_certificate(
    certificates: Iterable[Certificate],
    emitter_id: str,
) -> Certificate | None:
    """Return the single active certificate for one emitter or raise."""

    active_certificates = [
        certificate
        for certificate in certificates
        if certificate.emitter_id == emitter_id and certificate.is_active
    ]
    if len(active_certificates) > 1:
        raise DomainInvariantError(
            f"Emitter {emitter_id} has more than one active certificate."
        )
    if not active_certificates:
        return None
    return active_certificates[0]
