"""Fiscal checks a typed document must pass before it is created.

They run at creation so the caller gets a typed ``422`` instead of a
document that fails later in the worker (DECISIONES F01): the worker and the
XML builder repeat them, because a document can wait in the queue while the
emitter changes.
"""

from __future__ import annotations

from kilasifen.domain.common.errors import UnprocessableEntityError
from kilasifen.domain.documents.emitter_identity import (
    find_emitter_identity_mismatch,
)
from kilasifen.domain.emitters.models import EmitterSummary

#: Typed contracts whose XML the platform builds from the emitter profile.
TYPED_FISCAL_CONTRACTS = frozenset({"factura_v1", "nota_credito_v1", "nota_debito_v1"})


def typed_fiscal_payload(payload_snapshot: dict | None) -> dict | None:
    """Return the typed payload of a fiscal contract, or ``None`` for raw XML."""

    if not isinstance(payload_snapshot, dict):
        return None
    typed_contract = payload_snapshot.get("typed_contract")
    if not isinstance(typed_contract, dict):
        return None
    if str(typed_contract.get("contract") or "").strip() not in TYPED_FISCAL_CONTRACTS:
        return None
    typed_payload = typed_contract.get("payload")
    return typed_payload if isinstance(typed_payload, dict) else None


def require_emitter_fiscal_identity(
    emitter: EmitterSummary, typed_payload: dict
) -> None:
    """Refuse a document whose emitter cannot fill ``gEmis`` truthfully.

    - The emitter must have a fiscal profile (MT v150 D103-D132 "Debe
      corresponder a lo declarado en el RUC"): ``emitters.fiscal_profile_required``.
    - ``emisor`` and ``tipo_contribuyente`` of the payload may repeat the
      emitter identity but not change it (A002/1000, D101/0142, C004/1101):
      ``documents.emisor.identity_mismatch``.
    """

    profile = emitter.fiscal_profile
    if profile is None:
        raise UnprocessableEntityError(
            "emitters.fiscal_profile_required",
            details={"emitter_id": emitter.id},
        )
    mismatch = find_emitter_identity_mismatch(
        typed_payload,
        ruc=emitter.ruc,
        dv=emitter.dv,
        legal_name=emitter.legal_name,
        taxpayer_type=profile.taxpayer_type,
    )
    if mismatch is not None:
        raise UnprocessableEntityError(
            "documents.emisor.identity_mismatch",
            details={"field": mismatch},
        )
