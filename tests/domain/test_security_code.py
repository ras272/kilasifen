import pytest

from kilasifen.domain.documents.security_code import (
    InvalidSecurityCodeError,
    generate_security_code,
    normalize_security_code,
)


def test_generated_code_has_nine_digits_in_the_official_range() -> None:
    codes = {generate_security_code(1) for _ in range(200)}

    assert all(len(code) == 9 and code.isdigit() for code in codes)
    assert all(1 <= int(code) <= 999_999_999 for code in codes)
    # Random, not a constant: 200 draws from 999 999 999 values never collide.
    assert len(codes) == 200


def test_generated_code_is_drawn_again_when_it_equals_the_number() -> None:
    draws = iter([41, 41, 7])  # randbelow(n) + 1 -> 42, 42, 8

    code = generate_security_code(42, randbelow=lambda _limit: next(draws))

    assert code == "000000008"


def test_generated_code_covers_the_whole_range() -> None:
    lowest = generate_security_code(5, randbelow=lambda _limit: 0)
    highest = generate_security_code(5, randbelow=lambda limit: limit - 1)

    assert lowest == "000000001"
    assert highest == "999999999"


@pytest.mark.parametrize(
    ("raw", "expected"), [(7, "000000007"), ("123456789", "123456789")]
)
def test_caller_code_is_padded_to_nine_digits(raw, expected: str) -> None:
    assert normalize_security_code(raw, document_number=1) == expected


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        ("0", "documents.codigo_seguridad.zero"),
        ("000000000", "documents.codigo_seguridad.zero"),
        ("1234567890", "documents.codigo_seguridad.invalid_format"),
        ("12A", "documents.codigo_seguridad.invalid_format"),
        ("25", "documents.codigo_seguridad.equals_numero"),
        ("000000025", "documents.codigo_seguridad.equals_numero"),
    ],
)
def test_caller_code_outside_the_rules_is_rejected(raw: str, code: str) -> None:
    with pytest.raises(InvalidSecurityCodeError) as raised:
        normalize_security_code(raw, document_number=25)

    assert raised.value.code == code
