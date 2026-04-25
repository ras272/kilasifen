"""Certificate application service layer."""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.serialization import pkcs12

from kilasifen.domain.certificates.models import Certificate
from kilasifen.domain.common.errors import ConflictError, NotFoundError
from kilasifen.infrastructure.crypto.certificate_store import EncryptedCertificateStore
from kilasifen.repositories.certificates import CertificateRepository
from kilasifen.repositories.emitters import EmitterRepository


class CertificateService:
    """Use cases for certificate management."""

    def __init__(
        self,
        certificate_repository: CertificateRepository,
        emitter_repository: EmitterRepository,
        certificate_store: EncryptedCertificateStore,
    ):
        self.certificate_repository = certificate_repository
        self.emitter_repository = emitter_repository
        self.certificate_store = certificate_store

    def upload_certificate(
        self,
        *,
        emitter_id: str,
        logical_name: str,
        password: str,
        p12_bytes: bytes,
    ) -> Certificate:
        if self.emitter_repository.get(emitter_id) is None:
            raise NotFoundError("emitters.not_found")

        certificate = self._extract_metadata(p12_bytes, password)
        encrypted_p12 = self.certificate_store.encrypt_bytes(p12_bytes)
        encrypted_password = self.certificate_store.encrypt_text(password)
        timestamp = _now()

        record = Certificate(
            id=str(uuid4()),
            emitter_id=emitter_id,
            logical_name=logical_name,
            encrypted_p12=encrypted_p12,
            encrypted_password=encrypted_password,
            fingerprint=certificate["fingerprint"],
            serial_number=certificate["serial_number"],
            subject_summary=certificate["subject_summary"],
            detected_ruc=certificate["detected_ruc"],
            valid_from=certificate["valid_from"],
            valid_until=certificate["valid_until"],
            is_active=False,
            status="uploaded",
            created_at=timestamp,
            updated_at=timestamp,
        )
        return self.certificate_repository.save(record)

    def list_certificates(self, emitter_id: str) -> list[Certificate]:
        if self.emitter_repository.get(emitter_id) is None:
            raise NotFoundError("emitters.not_found")
        return self.certificate_repository.list_for_emitter(emitter_id)

    def activate_certificate(self, certificate_id: str) -> Certificate:
        target = self.certificate_repository.get(certificate_id)
        if target is None:
            raise NotFoundError("certificates.not_found")

        certificates = self.certificate_repository.list_for_emitter(target.emitter_id)
        activated: Certificate | None = None
        self.certificate_repository.deactivate_others(target.emitter_id, certificate_id)
        for certificate in certificates:
            updated = replace(
                certificate,
                is_active=certificate.id == certificate_id,
                updated_at=_now(),
            )
            saved = self.certificate_repository.save(updated)
            if saved.id == certificate_id:
                activated = saved

        if activated is None:
            raise ConflictError("certificates.activation_failed")
        return activated

    def _extract_metadata(self, p12_bytes: bytes, password: str) -> dict[str, object]:
        _private_key, certificate, _extra = pkcs12.load_key_and_certificates(
            p12_bytes,
            password.encode(),
        )
        if certificate is None:
            raise ConflictError("certificates.invalid_pkcs12")

        return {
            "fingerprint": certificate.fingerprint(hashes.SHA256()).hex(),
            "serial_number": str(certificate.serial_number),
            "subject_summary": certificate.subject.rfc4514_string(),
            "detected_ruc": _extract_ruc(certificate),
            "valid_from": _certificate_not_valid_before(certificate),
            "valid_until": _certificate_not_valid_after(certificate),
        }


def _extract_ruc(certificate: x509.Certificate) -> str | None:
    subject = certificate.subject.rfc4514_string()
    if "serialNumber=" not in subject:
        return None
    for part in subject.split(","):
        part = part.strip()
        if part.startswith("serialNumber="):
            return part.removeprefix("serialNumber=")
    return None


def _certificate_not_valid_before(certificate: x509.Certificate) -> datetime:
    if hasattr(certificate, "not_valid_before_utc"):
        return certificate.not_valid_before_utc
    return certificate.not_valid_before.replace(tzinfo=UTC)


def _certificate_not_valid_after(certificate: x509.Certificate) -> datetime:
    if hasattr(certificate, "not_valid_after_utc"):
        return certificate.not_valid_after_utc
    return certificate.not_valid_after.replace(tzinfo=UTC)


def _now() -> datetime:
    return datetime.now(UTC)
