"""Fiscal checks a typed document must pass before it is created.

They run at creation so the caller gets a typed ``422`` instead of a
document that fails later in the worker (DECISIONES F01): the worker and the
XML builder repeat them, because a document can wait in the queue while the
emitter changes.
"""

from __future__ import annotations

from datetime import datetime

from kilasifen.domain.common.errors import UnprocessableEntityError
from kilasifen.domain.documents.emitter_identity import (
    find_emitter_identity_mismatch,
)
from kilasifen.domain.documents.fiscal_dates import (
    emission_window_error,
    parse_sifen_datetime,
    transmission_warnings,
)
from kilasifen.domain.documents.security_code import (
    InvalidSecurityCodeError,
    generate_security_code,
    normalize_security_code,
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


def resolve_security_code(typed_payload: dict) -> str:
    """Return the ``dCodSeg`` the document will keep for its whole life.

    A caller-supplied ``codigo_seguridad`` is validated (``422`` when it is
    zero, not nine digits or equal to the document number); otherwise a
    random one is generated with ``secrets`` (MT v150 §10.3, XSD ``tiCodSe``).
    """

    number = _document_number(typed_payload)
    provided = typed_payload.get("codigo_seguridad")
    try:
        if provided is not None:
            return normalize_security_code(provided, document_number=number)
        return generate_security_code(number)
    except InvalidSecurityCodeError as exc:
        raise UnprocessableEntityError(exc.code) from exc


def _document_number(typed_payload: dict) -> int:
    try:
        return int(str(typed_payload.get("numero")))
    except (TypeError, ValueError):
        # Without a number nothing can collide with it; the builder refuses
        # the document later because dNumDoc is mandatory.
        return 0


def check_emission_date(typed_payload: dict, *, now: datetime) -> tuple[str, ...]:
    """Refuse a ``dFeEmiDE`` SIFEN would reject and report extemporaneous ones.

    - Outside the window (MT v150 D002: 1150 over 720 h late, 1151 over 120 h
      ahead, 1156 before 2018-11-22): ``422`` with that code.
    - More than 120 h before ``now``: accepted, but SIFEN approves it with
      observation 1005 (MT v150 §6.2.1); the warning code is returned.

    Without ``fecha_emision`` the builder uses the time it runs, always inside
    the window.
    """

    raw = typed_payload.get("fecha_emision")
    if raw is None:
        raw = typed_payload.get("fecha")
    if raw is None:
        return ()
    try:
        emission = parse_sifen_datetime(raw)
    except ValueError as exc:
        raise UnprocessableEntityError("documents.fecha_emision.invalid") from exc
    error = emission_window_error(emission, now)
    if error is not None:
        raise UnprocessableEntityError(
            error, details={"fecha_emision": emission.isoformat()}
        )
    return tuple(transmission_warnings(emission=emission, now=now))
