"""Certificate application service layer."""

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

from kilasifen.application.emitters.guards import require_active_emitter
from kilasifen.domain.certificates.models import Certificate
from kilasifen.domain.common.errors import ConflictError, NotFoundError
from kilasifen.engine.sdk.signer import clear_pkcs12_signer_cache
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
        evict_cached_signers: Callable[[], None] = clear_pkcs12_signer_cache,
    ):
        self.certificate_repository = certificate_repository
        self.emitter_repository = emitter_repository
        self.certificate_store = certificate_store
        self.evict_cached_signers = evict_cached_signers

    def upload_certificate(
        self,
        *,
        emitter_id: str,
        logical_name: str,
        password: str,
        p12_bytes: bytes,
    ) -> Certificate:
        require_active_emitter(self.emitter_repository, emitter_id)

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

        require_active_emitter(self.emitter_repository, target.emitter_id)
        emitter = self.emitter_repository.get(target.emitter_id)
        if emitter is None:
            raise NotFoundError("emitters.not_found")
        self._validate_activation(target, emitter.ruc)

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
        # Activation replaces and deactivates the emitter's other certificates.
        # Drop the decrypted private keys this process keeps in the PKCS12
        # signer cache so a retired key does not stay resident in memory. The
        # cache is per process: worker processes keep their own until evicted.
        self.evict_cached_signers()
        return activated

    def activate_certificate_for_emitter(
        self,
        *,
        emitter_id: str,
        certificate_id: str,
    ) -> Certificate:
        target = self.certificate_repository.get(certificate_id)
        if target is None or target.emitter_id != emitter_id:
            raise NotFoundError("certificates.not_found")
        return self.activate_certificate(certificate_id)

    def _extract_metadata(self, p12_bytes: bytes, password: str) -> dict[str, object]:
        try:
            private_key, certificate, _extra = pkcs12.load_key_and_certificates(
                p12_bytes,
                password.encode(),
            )
        except (TypeError, ValueError) as exc:
            raise ConflictError("certificates.invalid_pkcs12") from exc
        if certificate is None or private_key is None:
            raise ConflictError("certificates.invalid_pkcs12")
        if (
            not isinstance(private_key, rsa.RSAPrivateKey)
            or private_key.key_size < 2_048
        ):
            raise ConflictError("certificates.unsupported_private_key")

        return {
            "fingerprint": certificate.fingerprint(hashes.SHA256()).hex(),
            "serial_number": str(certificate.serial_number),
            "subject_summary": certificate.subject.rfc4514_string(),
            "detected_ruc": _extract_ruc(certificate),
            "valid_from": _certificate_not_valid_before(certificate),
            "valid_until": _certificate_not_valid_after(certificate),
        }

    @staticmethod
    def _validate_activation(certificate: Certificate, emitter_ruc: str) -> None:
        now = _now()
        if certificate.valid_from is None or certificate.valid_until is None:
            raise ConflictError("certificates.validity_missing")
        if now < _as_utc(certificate.valid_from):
            raise ConflictError("certificates.not_yet_valid")
        if now >= _as_utc(certificate.valid_until):
            raise ConflictError("certificates.expired")

        detected_ruc = _normalize_ruc(certificate.detected_ruc)
        if detected_ruc is None:
            raise ConflictError("certificates.ruc_missing")
        if detected_ruc != _normalize_ruc(emitter_ruc):
            raise ConflictError("certificates.ruc_mismatch")


def _extract_ruc(certificate: x509.Certificate) -> str | None:
    values = certificate.subject.get_attributes_for_oid(NameOID.SERIAL_NUMBER)
    if not values:
        return None
    return _normalize_ruc(values[0].value)


def _certificate_not_valid_before(certificate: x509.Certificate) -> datetime:
    if hasattr(certificate, "not_valid_before_utc"):
        return certificate.not_valid_before_utc
    return certificate.not_valid_before.replace(tzinfo=timezone.utc)


def _certificate_not_valid_after(certificate: x509.Certificate) -> datetime:
    if hasattr(certificate, "not_valid_after_utc"):
        return certificate.not_valid_after_utc
    return certificate.not_valid_after.replace(tzinfo=timezone.utc)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_ruc(value: str | None) -> str | None:
    if not value:
        return None
    ruc_without_dv = value.strip().split("-", 1)[0]
    digits = "".join(character for character in ruc_without_dv if character.isdigit())
    return digits or None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
