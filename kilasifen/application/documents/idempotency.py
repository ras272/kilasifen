"""Canonical idempotency rules for fiscal document creation."""

from __future__ import annotations

import hashlib
import hmac
import json
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from kilasifen.domain.common.errors import ConflictError
from kilasifen.domain.documents.models import Document


@dataclass(frozen=True, slots=True)
class DocumentIntentFingerprint:
    """Stable digest of the request parameters that define one fiscal intent."""

    digest: str
    canonical_payload: str


def require_matching_idempotent_intent(
    existing: Document,
    *,
    external_id: str | None,
    document_type: str,
    payload_snapshot: dict | None,
    server_managed_numbering: bool,
) -> None:
    """Reject reuse of an idempotency key for different request parameters."""

    incoming = fingerprint_document_intent(
        external_id=external_id,
        document_type=document_type,
        payload_snapshot=payload_snapshot,
        server_managed_numbering=server_managed_numbering,
    )
    persisted = fingerprint_document_intent(
        external_id=existing.external_id,
        document_type=existing.document_type,
        payload_snapshot=existing.payload_snapshot,
        server_managed_numbering=server_managed_numbering,
    )
    if hmac.compare_digest(incoming.digest, persisted.digest):
        return

    mismatched_parameters = []
    if external_id != existing.external_id:
        mismatched_parameters.append("external_id")
    if document_type != existing.document_type:
        mismatched_parameters.append("document_type")
    if incoming.canonical_payload != persisted.canonical_payload:
        mismatched_parameters.append("payload")
    raise ConflictError(
        "documents.idempotency_key_conflict",
        details={
            "existing_document_id": existing.id,
            "mismatched_parameters": mismatched_parameters,
        },
    )


def fingerprint_document_intent(
    *,
    external_id: str | None,
    document_type: str,
    payload_snapshot: dict | None,
    server_managed_numbering: bool,
) -> DocumentIntentFingerprint:
    """Build a versioned SHA-256 fingerprint from canonical JSON request data."""

    canonical_payload = _canonical_json(
        _canonical_payload(
            payload_snapshot,
            server_managed_numbering=server_managed_numbering,
        )
    )
    canonical_intent = _canonical_json(
        {
            "version": 1,
            "external_id": external_id,
            "document_type": document_type,
            "payload": json.loads(canonical_payload),
        }
    )
    return DocumentIntentFingerprint(
        digest=hashlib.sha256(canonical_intent.encode("utf-8")).hexdigest(),
        canonical_payload=canonical_payload,
    )


def _canonical_payload(
    payload_snapshot: dict | None,
    *,
    server_managed_numbering: bool,
) -> dict | None:
    snapshot = deepcopy(payload_snapshot)
    if not server_managed_numbering or not isinstance(snapshot, dict):
        return snapshot

    typed_contract = snapshot.get("typed_contract")
    if not isinstance(typed_contract, dict):
        return snapshot
    typed_payload = typed_contract.get("payload")
    if not isinstance(typed_payload, dict):
        return snapshot

    normalized_payload = dict(typed_payload)
    normalized_payload.pop("numero", None)
    normalized_payload["establecimiento"] = _normalize_three_digits(
        normalized_payload.get("establecimiento"),
        default="001",
    )
    normalized_payload["punto"] = _normalize_three_digits(
        normalized_payload.get("punto"),
        default="001",
    )

    normalized_contract = dict(typed_contract)
    normalized_contract["payload"] = normalized_payload
    snapshot["typed_contract"] = normalized_contract
    for derived_field in ("generated_xml", "signed_xml", "doc_id"):
        snapshot.pop(derived_field, None)
    return snapshot


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _normalize_three_digits(value: Any, *, default: str) -> str:
    normalized = default if value is None else value
    try:
        return f"{int(str(normalized)):03d}"
    except (TypeError, ValueError):
        return str(normalized)
