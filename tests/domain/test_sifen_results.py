"""How siRecepDE answers are read (DECISIONES F60; MT v150 §9.1.3, cap. 12)."""

import pytest

from kilasifen.domain.common.sifen_results import (
    ReceptionState,
    classify_reception,
    normalize_result_state,
)


@pytest.mark.parametrize(
    "literal",
    [
        # MT v150 §9.1.3 PP050 (p. 46).
        "Aprobado con observación",
        # MT v150 cap. 12 (p. 145).
        "APROBADO CON OBSERVACIONES",
        # Guia de Mejores Practicas DNIT oct-2024 (p. 6).
        "Aprobado con Observación",
        "  aprobado   con observacion ",
    ],
)
def test_every_official_spelling_of_an_observed_approval_is_recognized(
    literal: str,
) -> None:
    assert (
        classify_reception(literal, ["1005"]) is ReceptionState.APPROVED_WITH_OBSERVATION
    )


def test_an_observed_approval_is_never_a_rejection_whatever_its_code() -> None:
    # The code that comes with an AO is NO DETERMINADO (0260 + 1005, 1005,
    # 0261 in secondary sources): only dEstRes decides.
    for codes in (["0260", "1005"], ["1005"], ["0261"], []):
        state = classify_reception("Aprobado con observación", codes)
        assert state is ReceptionState.APPROVED_WITH_OBSERVATION


@pytest.mark.parametrize(
    ("state_text", "codes", "expected"),
    [
        ("Aprobado", ["0260"], ReceptionState.APPROVED),
        ("APROBADO", [], ReceptionState.APPROVED),
        ("Rechazado", ["1330"], ReceptionState.REJECTED),
        # MT v150 §7.4 (p. 36): a WS error also comes as Rechazado.
        ("Rechazado", ["0160"], ReceptionState.REJECTED),
        (None, ["0260"], ReceptionState.APPROVED),
        (None, ["1330"], ReceptionState.UNKNOWN),
        (None, [], ReceptionState.UNKNOWN),
        ("En proceso", ["0260"], ReceptionState.UNKNOWN),
    ],
)
def test_reception_is_classified_by_dEstRes_and_only_then_by_0260(
    state_text: str | None,
    codes: list[str],
    expected: ReceptionState,
) -> None:
    assert classify_reception(state_text, codes) is expected


def test_normalization_drops_accents_case_and_extra_blanks() -> None:
    assert normalize_result_state(" Aprobado  con OBSERVACIÓN ") == (
        "aprobado con observacion"
    )
    assert normalize_result_state(None) == ""
