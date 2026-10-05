"""Which document states may hand out a KuDE.

The KuDE is the graphic representation of a DE. It can be delivered before
SIFEN approves the DE (validacion posterior, MT v150 §6.2 p. 24), but it is
only valid once SIFEN approves it and as long as it matches the DTE (MT v150
§6.4 p. 26; Dto 872/2023 Arts. 4 and 26; RG 23/2019 Art. 15). So:

- approved documents (any ``approved*`` state) and documents still on their
  way to SIFEN have a KuDE;
- a rejected DE never becomes a DTE (MT v150 §6.4), a ``failed`` document
  was never accepted, a cancelled DTE lost its validity (Dto 872/2023 Art.
  30) and an inutilized number has no DE (Dto 872/2023 Art. 31): no KuDE.

Any other state is refused too: a KuDE is not handed out for a state whose
fiscal meaning is unknown.
"""

from __future__ import annotations

from kilasifen.domain.common.fiscal_states import DOCUMENT_PENDING_STATUSES

#: States whose KuDE is refused because the document is not, and will not
#: be, a valid DTE.
KUDE_REFUSED_STATUSES = frozenset({"rejected", "failed", "inutilized", "cancelled"})

_APPROVED_PREFIX = "approved"


def normalize_kude_status(status: str | None) -> str:
    """Compare states case- and blank-insensitively."""

    return str(status or "").strip().lower()


def is_kude_available(status: str | None) -> bool:
    """Return whether a document in ``status`` may hand out its KuDE."""

    normalized = normalize_kude_status(status)
    if normalized in KUDE_REFUSED_STATUSES:
        return False
    return normalized.startswith(_APPROVED_PREFIX) or (
        normalized in DOCUMENT_PENDING_STATUSES
    )
