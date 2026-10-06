"""SIFEN result codes and how the platform reads them.

Sources: Manual Tecnico SIFEN v150 (10/09/2019) and Notas Tecnicas 01-27
(the latest is NT 27 of 09/03/2026; none changes these codes), plus the DNIT
"Guia de Mejores Practicas para la Gestion del Envio de DE" (oct-2024).
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable
from enum import Enum

#: siRecepDE: "Autorizacion del DE satisfactoria" (MT v150 §12.3.1.3 BC01,
#: p. 154).
RECEPTION_APPROVED_CODE = "0260"

#: siConsDE: the CDC exists as an approved DTE and ``xContenDE`` carries it
#: (MT v150 Tabla G p. 51; Guia MP oct-2024 p. 12).
QUERY_FOUND_CODE = "0422"

#: siConsDE: "El DE no existe o no esta aprobado" (Guia MP oct-2024 p. 12,
#: which refines "CDC inexistente" of MT v150 Tabla G p. 51).
QUERY_NOT_FOUND_OR_NOT_APPROVED_CODE = "0420"

#: siRecepEvento: "Evento registrado correctamente" (MT v150 §12.3.6.3 BU01,
#: p. 158). 0260 and 0300 belong to other services.
EVENT_REGISTERED_CODE = "0600"

#: 1001 "CDC duplicado" and 1002 "Documento electronico duplicado" are only
#: raised when another document is already AUTHORIZED (MT v150 §12.4 val. 2-3,
#: p. 159): the CDC must be queried before the rejection is believed.
DUPLICATE_DOCUMENT_CODES = frozenset({"1001", "1002"})

#: Generic server failures that SIFEN reports with state R: 0161 "Servidor de
#: procesamiento momentaneamente sin respuesta" and 0162 "Servidor de
#: procesamiento paralizado" (MT v150 §12.2.6, p. 153).
SERVER_FAILURE_CODES = frozenset({"0161", "0162"})

#: AE01 "XML malformado": a generic rejection of the input message of any
#: web service, in the same group as 0161/0162 (MT v150 §12.2.6, p. 153).
XML_MALFORMED_CODE = "0160"

def is_retryable_rejection(answer: Iterable[tuple[str, str | None]]) -> bool:
    """Whether a siRecepDE Rechazado lets the same signed DE travel again.

    ``answer`` holds the ``(code, message)`` of every ``gResProc``.

    - 0161/0162 in any message: server failures (DECISIONES F64).
    - 0160 alone and without a validation detail (DECISIONES F67). SIFEN
      reports a content error as "XML malformado: <detalle>" (Guia de
      Mejores Practicas, oct-2024, p. 11), which needs a corrected DE and
      stays final. A bare "XML Mal Formado." was answered by the test
      environment on 2026-10-06 to valid requests that passed seconds later.
      MT v150 §6.5 (p. 26) lets a rejected DE keep its CDC and be submitted
      again "cuantas veces sea necesario".
    """

    pairs = [(str(code), message) for code, message in answer]
    codes = {code for code, _ in pairs}
    if codes & SERVER_FAILURE_CODES:
        return True
    return codes == {XML_MALFORMED_CODE} and not any(
        _validation_detail(message) for _, message in pairs
    )


def _validation_detail(message: str | None) -> str:
    """What follows "XML malformado:" in a 0160 message, if anything."""

    _, separator, detail = (message or "").partition(":")
    return detail.strip() if separator else ""


#: Cancellation answers that a retry can get although an earlier attempt was
#: registered: 4002 (CDC no longer approved), 4003 (duplicate), 4009 and 4010
#: (deadline) (MT v150 §11.6.1, p. 134). Which one SIFEN returns is NO
#: DETERMINADO, so the CDC is queried before believing any of them.
CANCELLATION_SUSPECT_CODES = frozenset({"4002", "4003", "4009", "4010"})

#: GEC002b: "El DTE ya se encuentra con un evento que se esta requiriendo
#: nuevamente (Duplicidad)" (MT v150 §11.6.1, p. 134). SIFEN itself says the
#: cancellation is already registered, so this answer is never read as a
#: final rejection.
CANCELLATION_DUPLICATE_CODE = "4003"

#: Inutilization: "existen numeros de DE ya inutilizados en SIFEN" (MT v150
#: §11.6.2, p. 135).
INUTILIZATION_OVERLAP_CODE = "4066"


class ReceptionState(str, Enum):
    """How the platform reads one siRecepDE answer."""

    APPROVED = "approved"
    APPROVED_WITH_OBSERVATION = "approved_with_observation"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


def normalize_result_state(text: str | None) -> str:
    """Lowercase ``text``, drop accents and collapse blanks.

    The literal of ``dEstRes`` differs between sources ("Aprobado con
    observacion" in MT v150 §9, "APROBADO CON OBSERVACIONES" in its chapter
    12, "Aprobado con Observacion" in the Guia MP oct-2024), so it is only
    compared normalized.
    """

    decomposed = unicodedata.normalize("NFKD", str(text or ""))
    without_accents = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return " ".join(without_accents.lower().split())


def classify_reception(
    state_text: str | None,
    codes: tuple[str, ...] | list[str],
) -> ReceptionState:
    """Read a siRecepDE answer from ``dEstRes`` and its result codes.

    ``dEstRes`` decides (MT v150 §9.1.3 PP050 p. 46; XSD
    protProcesDE_v150.xsd): "Aprobado" and "Aprobado con observacion" are
    valid DTE (MT v150 cap. 12 p. 145) and "Rechazado" is a rejection. Without
    ``dEstRes`` only 0260 proves an approval; anything else is unknown and
    must be reconciled by CDC, never read as a rejection.
    """

    state = normalize_result_state(state_text)
    if state.startswith("aprobado con observ"):
        return ReceptionState.APPROVED_WITH_OBSERVATION
    if state.startswith("aprobado"):
        return ReceptionState.APPROVED
    if state.startswith("rechazad"):
        return ReceptionState.REJECTED
    if not state and RECEPTION_APPROVED_CODE in codes:
        return ReceptionState.APPROVED
    return ReceptionState.UNKNOWN
