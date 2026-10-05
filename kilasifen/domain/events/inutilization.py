"""Inutilization rules that do not depend on persistence (DECISIONES F72).

- Which document numbers may be inutilized: a number is a DTE once SIFEN
  approved it, and SIFEN refuses to inutilize a DTE (4065, MT v150 §11.6.2
  p. 135). Numbers without document, rejected by SIFEN, failed by local
  validation or queued and aborted are not DTE and must be inutilized when
  they will not be used (MT v150 §11.1.1 p. 112, §6.5 pp. 26-27; Dto
  872/2023 Arts. 29 and 31; RG 23/2019 Art. 23). A cancelled DTE is blocked
  as a precaution (whether SIFEN applies 4065 to it is NO DETERMINADO), and
  a document that may be at SIFEN is blocked until a query by CDC answers
  0420.
- The deadline: the first 15 days of the month after the number was
  consumed (MT v150 §6.2.1 p. 25; Tabla J p. 117; RG 23/2019 Art. 23).
  SIFEN has no rejection code for it (MT v150 §11.6.2) and the "plazo del
  sistema" is the timbrado validity, which has no end (RG 23/2019 Art. 12),
  so a late inutilization is only flagged, never refused.
"""

from __future__ import annotations

from datetime import date

#: Document states whose number may be inutilized, provided no job is
#: about to send the document.
INUTILIZABLE_DOCUMENT_STATUSES = frozenset({"rejected", "failed", "queued"})

#: Job states in which the document can still be sent to SIFEN.
ACTIVE_JOB_STATUSES = frozenset({"queued", "processing", "retry_scheduled"})


def is_inutilizable(document_status: str, job_status: str | None) -> bool:
    """Whether a numbered document may have its number inutilized."""

    if document_status not in INUTILIZABLE_DOCUMENT_STATUSES:
        return False
    return job_status not in ACTIVE_JOB_STATUSES


def inutilization_deadline(consumed_on: date) -> date:
    """Last day to inutilize a number consumed on ``consumed_on``.

    Day 15 of the following month, inclusive ("dentro de los 15 primeros
    dias del mes siguiente", MT v150 Tabla J p. 117).
    """

    if consumed_on.month == 12:
        return date(consumed_on.year + 1, 1, 15)
    return date(consumed_on.year, consumed_on.month + 1, 15)
