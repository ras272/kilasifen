"""Certificate application service layer."""

import re
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
from kilasifen.engine.sdk.fiscal import calculate_mod11_dv
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
        self._validate_activation(target, emitter.ruc, emitter.dv)

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
        # Defense in depth: drop the decrypted keys this process may hold in
        # the per-process PKCS12 signer cache. Signing happens in the workers,
        # which drop that cache at the end of every document and event job.
        # This runs before the request transaction commits, so a signer in
        # this same process could still cache the old key until it commits.
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
    def _validate_activation(
        certificate: Certificate, emitter_ruc: str, emitter_dv: str
    ) -> None:
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
        detected_dv = _detected_dv(certificate.detected_ruc)
        if detected_dv is not None and detected_dv != emitter_dv.strip():
            raise ConflictError("certificates.ruc_mismatch")


#: MT v150 §7.5: "RUC" + number + "-" + check digit, without spaces.
_RUC_SERIAL_PATTERN = re.compile(r"^RUC([1-9][0-9]*[0-9A-D]?)-([0-9])$")
_RUC_BODY_PATTERN = re.compile(r"[0-9]+[A-D]?")
_DER_STRING_TAGS = {0x0C: "utf-8", 0x13: "ascii", 0x16: "ascii"}


def _extract_ruc(certificate: x509.Certificate) -> str | None:
    """Return the emitter RUC the certificate declares (``RUC`` or ``RUC-DV``).

    MT v150 §7.5 (pp. 37-38): a persona juridica certificate carries the RUC
    in the Subject ``SerialNumber`` (OID 2.5.4.5); a persona fisica one (a
    dependent of the taxpayer) carries the RUC of the entity in the
    ``SubjectAlternativeName`` ``SerialNumber``, so the SAN wins. The format
    is ``RUC<number>-<DV>`` and the DV is checked with modulo 11 (0122/0142).
    Reading the SAN from a ``directoryName`` or an ``otherName`` is a
    technical inference: the MT does not say which GeneralName carries it.
    """

    for value in _san_serial_numbers(certificate):
        ruc = _ruc_from_serial(value)
        if ruc is not None:
            return ruc
    values = certificate.subject.get_attributes_for_oid(NameOID.SERIAL_NUMBER)
    if not values:
        return None
    serial = str(values[0].value).strip()
    return _ruc_from_serial(serial) or _normalize_ruc(serial)


def _ruc_from_serial(value: str) -> str | None:
    match = _RUC_SERIAL_PATTERN.match(value.strip().upper())
    if match is None:
        return None
    ruc, dv = match.groups()
    if int(dv) != calculate_mod11_dv(ruc):
        raise ConflictError("certificates.ruc_dv_invalid")
    return f"{ruc}-{dv}"


def _san_serial_numbers(certificate: x509.Certificate) -> list[str]:
    try:
        names = certificate.extensions.get_extension_for_class(
            x509.SubjectAlternativeName
        ).value
    except x509.ExtensionNotFound:
        return []
    values: list[str] = []
    for name in names:
        if isinstance(name, x509.DirectoryName):
            values.extend(
                str(attribute.value)
                for attribute in name.value.get_attributes_for_oid(
                    NameOID.SERIAL_NUMBER
                )
            )
        elif isinstance(name, x509.OtherName) and name.type_id == (
            NameOID.SERIAL_NUMBER
        ):
            decoded = _der_string(name.value)
            if decoded is not None:
                values.append(decoded)
    return values


def _der_string(data: bytes) -> str | None:
    """Decode a DER UTF8String/PrintableString/IA5String, optionally [0]-wrapped."""

    if len(data) >= 2 and data[0] == 0xA0:
        inner = _der_content(data)
        if inner is None:
            return None
        data = inner
    if not data or data[0] not in _DER_STRING_TAGS:
        return None
    content = _der_content(data)
    if content is None:
        return None
    try:
        return content.decode(_DER_STRING_TAGS[data[0]])
    except UnicodeDecodeError:
        return None


def _der_content(data: bytes) -> bytes | None:
    if len(data) < 2:
        return None
    length = data[1]
    offset = 2
    if length & 0x80:
        size = length & 0x7F
        if size == 0 or len(data) < 2 + size:
            return None
        length = int.from_bytes(data[2 : 2 + size], "big")
        offset = 2 + size
    if len(data) < offset + length:
        return None
    return data[offset : offset + length]


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
    """RUC without prefix nor DV; keeps the final letter tRuc allows (A-D)."""

    if not value:
        return None
    ruc_without_dv = value.strip().upper().split("-", 1)[0]
    if ruc_without_dv.startswith("RUC"):
        ruc_without_dv = ruc_without_dv[3:]
    match = _RUC_BODY_PATTERN.search(ruc_without_dv)
    return match.group(0) if match else None


def _detected_dv(value: str | None) -> str | None:
    if not value or "-" not in value:
        return None
    dv = value.split("-", 1)[1].strip()
    return dv or None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
