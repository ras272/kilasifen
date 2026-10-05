import pytest

from kilasifen.application.emitters.identity import (
    normalize_csc_id,
    validate_csc,
    validate_legal_name,
    validate_tax_id,
)
from kilasifen.domain.common.errors import UnprocessableEntityError

# Official vectors: MT v150 p. 211 ("RUC Emisor: 44444401-7") and the RUC of
# the CDC example of the DNIT Guía de Mejores Prácticas (oct-2024, p. 11).
_VALID_TAX_IDS = [("44444401", "7"), ("80025298", "5")]


@pytest.mark.parametrize(("ruc", "dv"), _VALID_TAX_IDS)
def test_valid_tax_ids_pass(ruc: str, dv: str) -> None:
    validate_tax_id(ruc, dv)


def test_short_ruc_with_three_characters_is_valid() -> None:
    validate_tax_id("123", "6")


@pytest.mark.parametrize("ruc", ["12", "123456789", "01234567", "8002413E", "8002-41"])
def test_ruc_outside_xsd_truc_is_rejected(ruc: str) -> None:
    with pytest.raises(UnprocessableEntityError, match="emitters.ruc_invalid"):
        validate_tax_id(ruc, "0")


def test_dv_that_is_not_the_modulo_11_is_rejected() -> None:
    with pytest.raises(UnprocessableEntityError, match="emitters.dv_mismatch"):
        validate_tax_id("44444401", "8")


@pytest.mark.parametrize("dv", ["", "10", "A"])
def test_dv_must_be_a_single_digit(dv: str) -> None:
    with pytest.raises(UnprocessableEntityError, match="emitters.dv_mismatch"):
        validate_tax_id("44444401", dv)


@pytest.mark.parametrize("name", ["ABC", "   ", "X" * 256])
def test_legal_name_outside_tdnombre_is_rejected(name: str) -> None:
    with pytest.raises(UnprocessableEntityError, match="emitters.legal_name_invalid"):
        validate_legal_name(name)


def test_csc_must_have_32_alphanumeric_characters() -> None:
    validate_csc("ABCD0000000000000000000000000000")
    for invalid in ("ABCD", "ABCD-000000000000000000000000000", "A" * 33):
        with pytest.raises(UnprocessableEntityError, match="emitters.csc_invalid"):
            validate_csc(invalid)


@pytest.mark.parametrize(
    ("raw", "normalized"), [("1", "0001"), ("0002", "0002"), ("9999", "9999")]
)
def test_csc_id_is_normalized_to_four_digits(raw: str, normalized: str) -> None:
    assert normalize_csc_id(raw) == normalized


@pytest.mark.parametrize("raw", ["0", "0000", "10000", "A1", ""])
def test_csc_id_outside_1_to_9999_is_rejected(raw: str) -> None:
    with pytest.raises(UnprocessableEntityError, match="emitters.csc_id_invalid"):
        normalize_csc_id(raw)
