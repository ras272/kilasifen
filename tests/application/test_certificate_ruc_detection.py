"""RUC of the emitter inside the signing certificate (MT v150 §7.5)."""

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

from kilasifen.application.certificates.service import CertificateService
from kilasifen.domain.common.errors import ConflictError
from kilasifen.domain.emitters.models import Emitter

_PASSWORD = "fictional-password"
_KEY = rsa.generate_private_key(public_exponent=65_537, key_size=2_048)


def _pkcs12(
    *, subject_serial: str | None, san: list[x509.GeneralName] | None = None
) -> bytes:
    attributes = [x509.NameAttribute(NameOID.COMMON_NAME, "Titular Ficticio")]
    if subject_serial is not None:
        attributes.append(x509.NameAttribute(NameOID.SERIAL_NUMBER, subject_serial))
    name = x509.Name(attributes)
    now = datetime.now(timezone.utc)
    builder = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(_KEY.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=30))
    )
    if san:
        builder = builder.add_extension(
            x509.SubjectAlternativeName(san), critical=False
        )
    certificate = builder.sign(_KEY, hashes.SHA256())
    return pkcs12.serialize_key_and_certificates(
        name=b"ficticio",
        key=_KEY,
        cert=certificate,
        cas=None,
        encryption_algorithm=serialization.BestAvailableEncryption(
            _PASSWORD.encode()
        ),
    )


def _service() -> CertificateService:
    certificate_repository = Mock()
    certificate_repository.save.side_effect = lambda record: record
    emitter_repository = Mock()
    emitter_repository.get_status_for_update.return_value = "active"
    now = datetime.now(timezone.utc)
    emitter_repository.get.return_value = Emitter(
        id="emitter-1",
        external_id=None,
        ruc="44444401",
        dv="7",
        legal_name="EMISOR FICTICIO SA",
        tax_environment="test",
        status="active",
        csc=None,
        csc_id=None,
        created_at=now,
        updated_at=now,
    )
    store = Mock()
    store.encrypt_bytes.return_value = "encrypted"
    store.encrypt_text.return_value = "encrypted"
    return CertificateService(
        certificate_repository=certificate_repository,
        emitter_repository=emitter_repository,
        certificate_store=store,
        evict_cached_signers=Mock(),
    )


def _upload(p12: bytes):
    return _service().upload_certificate(
        emitter_id="emitter-1",
        logical_name="firma",
        password=_PASSWORD,
        p12_bytes=p12,
    )


def test_legal_entity_certificate_reads_the_subject_serial_number() -> None:
    record = _upload(_pkcs12(subject_serial="RUC44444401-7"))

    assert record.detected_ruc == "44444401-7"


def test_natural_person_certificate_reads_the_ruc_from_the_san() -> None:
    # The Subject serial is the holder's ID; the SAN carries the entity RUC.
    san = [
        x509.DirectoryName(
            x509.Name([x509.NameAttribute(NameOID.SERIAL_NUMBER, "RUC44444401-7")])
        )
    ]

    record = _upload(_pkcs12(subject_serial="CI1234567", san=san))

    assert record.detected_ruc == "44444401-7"


def test_san_other_name_with_the_serial_number_oid_is_read() -> None:
    printable = b"RUC44444401-7"
    der_value = bytes([0x13, len(printable)]) + printable
    san = [x509.OtherName(NameOID.SERIAL_NUMBER, der_value)]

    record = _upload(_pkcs12(subject_serial="CI1234567", san=san))

    assert record.detected_ruc == "44444401-7"


def test_ruc_with_a_wrong_check_digit_is_refused() -> None:
    with pytest.raises(ConflictError, match="certificates.ruc_dv_invalid"):
        _upload(_pkcs12(subject_serial="RUC44444401-8"))


def test_certificate_of_the_emitter_activates() -> None:
    service = _service()
    record = service.upload_certificate(
        emitter_id="emitter-1",
        logical_name="firma",
        password=_PASSWORD,
        p12_bytes=_pkcs12(subject_serial="RUC44444401-7"),
    )
    service.certificate_repository.get.return_value = record
    service.certificate_repository.list_for_emitter.return_value = [record]

    activated = service.activate_certificate(record.id)

    assert activated.is_active is True


def test_certificate_of_another_ruc_does_not_activate() -> None:
    service = _service()
    record = service.upload_certificate(
        emitter_id="emitter-1",
        logical_name="firma",
        password=_PASSWORD,
        p12_bytes=_pkcs12(subject_serial="RUC80025298-5"),
    )
    service.certificate_repository.get.return_value = record

    with pytest.raises(ConflictError, match="certificates.ruc_mismatch"):
        service.activate_certificate(record.id)
