"""Human formatting of KuDE amounts and dates (DECISIONES F51)."""

import pytest

from kilasifen.infrastructure.kude.formatting import format_amount, format_kude_date


@pytest.mark.parametrize(
    ("literal", "currency", "printed"),
    [
        # IVA with 8 decimals (NT 13) prints as whole guaranies.
        ("9090.90909091", "PYG", "9.091"),
        ("90909.09090909", "PYG", "90.909"),
        ("100000", "PYG", "100.000"),
        ("1234567.5", "PYG", "1.234.568"),
        ("0.4", "PYG", "0"),
        ("0", "PYG", "0"),
        # Other currencies print with two decimals, rounded half up.
        ("120.5", "USD", "120,50"),
        ("10.95454546", "USD", "10,95"),
        ("1234.565", "USD", "1.234,57"),
        ("0", "EUR", "0,00"),
        # Without a currency the amount is treated as guaranies.
        ("2500.5", None, "2.501"),
    ],
)
def test_amounts_print_rounded_from_the_exact_xml_value(literal, currency, printed):
    assert format_amount(literal, currency) == printed


@pytest.mark.parametrize("literal", ["", None, "  "])
def test_missing_amounts_print_nothing(literal):
    assert format_amount(literal, "PYG") == ""


def test_a_text_that_is_not_a_number_is_printed_unchanged():
    assert format_amount("N/A", "PYG") == "N/A"


def test_stamping_start_date_prints_as_dd_mm_aaaa():
    # NT 10 §1.11: C008 in the KuDE, e.g. "31-05-2018".
    assert format_kude_date("2018-05-31") == "31-05-2018"


@pytest.mark.parametrize("literal", ["31/05/2018", "", None])
def test_other_date_texts_print_unchanged(literal):
    assert format_kude_date(literal) == (literal or "")
