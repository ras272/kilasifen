"""How the KuDE prints XML values (MT v150 §13.2, §6.6 and §13.4; NT 10)."""

import pytest

from kilasifen.infrastructure.kude.formatting import format_decimal, format_kude_date


@pytest.mark.parametrize(
    ("literal", "printed"),
    [
        # MT v150 §13.4 examples: "." groups thousands ("110.000").
        ("110000", "110.000"),
        ("100", "100"),
        ("1234567", "1.234.567"),
        ("0", "0"),
        # IVA with 8 decimals (tMontoBase, other currencies) keeps every decimal.
        ("952.38095238", "952,38095238"),
        ("2727.27272727", "2.727,27272727"),
        ("3679.65367965", "3.679,65367965"),
        # Trailing zeros are digits of the literal too.
        ("120.50", "120,50"),
        ("120.5", "120,5"),
        ("0.4", "0,4"),
        # Longest tMontoBase literal (15 integer digits, 8 decimals).
        ("999999999999999.99999999", "999.999.999.999.999,99999999"),
    ],
)
def test_numbers_print_every_digit_of_the_xml_literal(literal, printed):
    assert format_decimal(literal) == printed


@pytest.mark.parametrize("literal", ["952.38095238", "2727.27272727", "120.50"])
def test_only_the_separators_change(literal):
    printed = format_decimal(literal)

    assert printed.replace(".", "").replace(",", ".") == literal


@pytest.mark.parametrize("literal", ["", None, "  "])
def test_missing_numbers_print_nothing(literal):
    assert format_decimal(literal) == ""


@pytest.mark.parametrize("literal", ["N/A", "1e5", "1.2.3", "-"])
def test_a_text_that_is_not_a_decimal_literal_is_printed_unchanged(literal):
    assert format_decimal(literal) == literal


def test_stamping_start_date_prints_as_dd_mm_aaaa():
    # NT 10 §1.11: C008 in the KuDE, e.g. "31-05-2018".
    assert format_kude_date("2018-05-31") == "31-05-2018"


@pytest.mark.parametrize("literal", ["31/05/2018", "", None])
def test_other_date_texts_print_unchanged(literal):
    assert format_kude_date(literal) == (literal or "")
