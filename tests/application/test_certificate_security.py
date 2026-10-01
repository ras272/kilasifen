from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from kilasifen.application.certificates.service import CertificateService
from kilasifen.domain.certificates.models import Certificate
from kilasifen.domain.common.errors import ConflictError
from kilasifen.domain.emitters.models import Emitter

_REFERENCE_NOW = datetime.now(timezone.utc)


@pytest.mark.parametrize(
    ("valid_from", "valid_until", "detected_ruc", "error_code"),
    [
        (
            _REFERENCE_NOW + timedelta(days=1),
            _REFERENCE_NOW + timedelta(days=2),
            "80024135",
            "certificates.not_yet_valid",
        ),
        (
            _REFERENCE_NOW - timedelta(days=2),
            _REFERENCE_NOW - timedelta(days=1),
            "80024135",
            "certificates.expired",
        ),
        (
            _REFERENCE_NOW - timedelta(days=1),
            _REFERENCE_NOW + timedelta(days=1),
            None,
            "certificates.ruc_missing",
        ),
        (
            _REFERENCE_NOW - timedelta(days=1),
            _REFERENCE_NOW + timedelta(days=1),
            "80111111",
            "certificates.ruc_mismatch",
        ),
    ],
)
def test_activation_rejects_invalid_certificate_metadata(
    valid_from: datetime,
    valid_until: datetime,
    detected_ruc: str | None,
    error_code: str,
) -> None:
    certificate = _certificate(
        valid_from=valid_from,
        valid_until=valid_until,
        detected_ruc=detected_ruc,
    )
    service = _service(certificate)

    with pytest.raises(ConflictError, match=error_code):
        service.activate_certificate(certificate.id)


def _service(certificate: Certificate) -> CertificateService:
    certificate_repository = Mock()
    certificate_repository.get.return_value = certificate
    emitter_repository = Mock()
    emitter_repository.get_status_for_update.return_value = "active"
    emitter_repository.get.return_value = Emitter(
        id=certificate.emitter_id,
        external_id="erp-test",
        ruc="80024135",
        dv="5",
        legal_name="Test Only",
        tax_environment="test",
        status="active",
        csc=None,
        csc_id=None,
        created_at=_now(),
        updated_at=_now(),
    )
    return CertificateService(
        certificate_repository=certificate_repository,
        emitter_repository=emitter_repository,
        certificate_store=Mock(),
    )


def _certificate(
    *,
    valid_from: datetime,
    valid_until: datetime,
    detected_ruc: str | None,
) -> Certificate:
    return Certificate(
        id="certificate-1",
        emitter_id="emitter-1",
        logical_name="principal",
        encrypted_p12="encrypted",
        encrypted_password="encrypted",
        fingerprint="fingerprint",
        serial_number="1",
        subject_summary="CN=Test Only",
        detected_ruc=detected_ruc,
        valid_from=valid_from,
        valid_until=valid_until,
        is_active=False,
        status="uploaded",
        created_at=_now(),
        updated_at=_now(),
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)
