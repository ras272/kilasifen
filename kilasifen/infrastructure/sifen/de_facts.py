"""Facts the platform reads back from a DE it built or signed.

The DE dates carry no time zone (MT v150 A004 p. 62 and D002 p. 65; XSD
``fecHhmmss``). They are read as Paraguay wall time, UTC-03:00 all year
since Ley 7354/2024 (no daylight saving time from 06/10/2024).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from xml.etree import ElementTree as ET

from kilasifen.domain.documents.models import Document

#: Hora oficial de Paraguay (Ley 7354/2024 Arts. 1-2).
PARAGUAY_TZ = timezone(timedelta(hours=-3), "PYT")


@dataclass(frozen=True, slots=True)
class DeFacts:
    """``dFecFirma`` (A004), ``dFeEmiDE`` (D002) and ``dNumTim`` (C004)."""

    signed_at: datetime | None
    issued_at: datetime | None
    timbrado: str | None


def read_de_facts(xml_text: str | None) -> DeFacts:
    """Read signature time, emission time and timbrado from ``xml_text``.

    Unparseable XML or missing fields give ``None`` values, never an error:
    callers use these facts for alerts and conservative bounds only.
    """

    root = _parse(xml_text)
    if root is None:
        return DeFacts(signed_at=None, issued_at=None, timbrado=None)
    return DeFacts(
        signed_at=_paraguay_time(_first_text(root, "dFecFirma")),
        issued_at=_paraguay_time(_first_text(root, "dFeEmiDE")),
        timbrado=_first_text(root, "dNumTim"),
    )


def parse_sifen_datetime(value: str | None) -> datetime | None:
    """Parse a SIFEN date-time; one without offset is Paraguay wall time.

    ``dFecProc`` follows ``fecUTC`` (``AAAA-MM-DDThh:mm:ss-03:00``, XSD
    SIFEN_Types_v141.xsd); the DE dates have no offset at all.
    """

    return _paraguay_time(value)


def paraguay_today() -> date:
    """Current date in Paraguay."""

    return datetime.now(PARAGUAY_TZ).date()


def approval_lower_bound(document: Document) -> datetime:
    """Earliest instant at which SIFEN can have approved ``document``.

    Used when the approval was learnt without ``dFecProc`` (a query by CDC
    carries no approval time: MT v150 §9.4.3 pp. 51-52). SIFEN rejects a
    ``dFecFirma`` later than its own clock (1004, MT v150 §12.4 p. 159), so
    for an approved DE ``dFecFirma`` precedes the approval; the document
    creation always does. The later of both is the tightest safe bound, and a
    cancellation window counted from it closes before SIFEN's own (DECISIONES
    F71).
    """

    created_at = _as_utc(document.created_at)
    signed_at = read_de_facts(document.signed_xml).signed_at
    if signed_at is None:
        return created_at
    return max(created_at, signed_at.astimezone(timezone.utc))


def _parse(xml_text: str | None) -> ET.Element | None:
    if not xml_text:
        return None
    try:
        return ET.fromstring(xml_text.encode("utf-8"))
    except ET.ParseError:
        return None


def _first_text(root: ET.Element, local_name: str) -> str | None:
    for element in root.iter():
        if not isinstance(element.tag, str):
            continue
        if element.tag.rsplit("}", 1)[-1] != local_name:
            continue
        value = (element.text or "").strip()
        if value:
            return value
    return None


def _paraguay_time(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        # Python < 3.11 fromisoformat does not accept the "Z" suffix.
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=PARAGUAY_TZ)
    return parsed


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
