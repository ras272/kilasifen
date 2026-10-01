"""Checks run right before the platform signs a DE.

The XML about to be signed already carries ``dFecFirma`` (the signing time,
set by the typed builder just before signing, or declared by a raw-XML
caller) and ``dFeEmiDE``. Before the signature:

- ``dFeEmiDE`` must be inside the transmission window (1150, 1151, 1156);
- ``dFecFirma`` cannot be after the current time (1004);
- the certificate must be valid at ``dFecFirma`` (2450, NT 16).

A failure raises :class:`SifenValidationError`, so the worker fails the
document locally instead of sending something SIFEN rejects for sure.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

from cryptography.hazmat.primitives.serialization import pkcs12

from kilasifen.domain.common.paraguay_time import PARAGUAY_TZ
from kilasifen.domain.documents.fiscal_dates import (
    emission_window_error,
    parse_sifen_datetime,
    signature_time_error,
)
from kilasifen.engine.sdk.errors import SifenValidationError

_NS = {"s": "http://ekuatia.set.gov.py/sifen/xsd"}


@dataclass(frozen=True, slots=True)
class DocumentDates:
    """``dFeEmiDE`` and ``dFecFirma`` as naive Paraguayan wall times."""

    emission: datetime
    signature: datetime


def read_document_dates(xml: str) -> DocumentDates:
    """Read ``dFeEmiDE`` and ``dFecFirma`` from an ``rDE``."""

    try:
        root = ET.fromstring(xml.encode("utf-8"))
    except ET.ParseError as exc:
        raise SifenValidationError("documents.xml.unreadable") from exc
    return DocumentDates(
        emission=_date_field(root, "s:DE/s:gDatGralOpe/s:dFeEmiDE", "dFeEmiDE"),
        signature=_date_field(root, "s:DE/s:dFecFirma", "dFecFirma"),
    )


def assert_ready_to_sign(
    xml: str,
    *,
    now: datetime,
    certificate_bytes: bytes,
    certificate_password: str,
) -> DocumentDates:
    """Refuse to sign a DE that SIFEN would reject for its dates."""

    dates = read_document_dates(xml)
    for error in (
        emission_window_error(dates.emission, now),
        signature_time_error(dates.signature, now),
    ):
        if error is not None:
            raise SifenValidationError(error)
    valid_from, valid_until = _certificate_validity(
        certificate_bytes, certificate_password
    )
    signed_at = dates.signature.replace(tzinfo=PARAGUAY_TZ)
    if not valid_from <= signed_at < valid_until:
        raise SifenValidationError("documents.certificate.not_valid_at_signature")
    return dates


def _date_field(root: ET.Element, path: str, name: str) -> datetime:
    node = root.find(path, _NS)
    if node is None or not node.text:
        raise SifenValidationError(f"documents.xml.{name}_missing")
    try:
        return parse_sifen_datetime(node.text)
    except ValueError as exc:
        raise SifenValidationError(f"documents.xml.{name}_invalid") from exc


def _certificate_validity(
    certificate_bytes: bytes, certificate_password: str
) -> tuple[datetime, datetime]:
    try:
        _key, certificate, _extra = pkcs12.load_key_and_certificates(
            certificate_bytes, certificate_password.encode()
        )
    except (TypeError, ValueError) as exc:
        raise SifenValidationError("documents.certificate.unreadable") from exc
    if certificate is None:
        raise SifenValidationError("documents.certificate.unreadable")
    return (
        _aware(certificate, "not_valid_before"),
        _aware(certificate, "not_valid_after"),
    )


def _aware(certificate, attribute: str) -> datetime:
    utc_value = getattr(certificate, f"{attribute}_utc", None)
    if utc_value is not None:
        return utc_value
    return getattr(certificate, attribute).replace(tzinfo=timezone.utc)
