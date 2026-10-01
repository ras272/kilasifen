from dataclasses import replace

import pytest

from kilasifen.application.emitters.fiscal_profile import normalize_fiscal_profile
from kilasifen.domain.common.errors import UnprocessableEntityError
from kilasifen.domain.emitters.fiscal_profile import (
    EconomicActivity,
    fiscal_profile_from_dict,
    fiscal_profile_to_dict,
)
from kilasifen.testing.fiscal_profiles import (
    fictional_fiscal_profile,
    fictional_fiscal_profile_payload,
)


def test_profile_round_trips_through_its_persisted_form() -> None:
    payload = fictional_fiscal_profile_payload()
    payload["establecimientos"] = [
        {**payload["domicilio"], "establecimiento": "002", "direccion": "SUCURSAL"}
    ]

    profile = fiscal_profile_from_dict(payload)

    assert fiscal_profile_to_dict(profile) == payload
    assert profile.address_for("002").street == "SUCURSAL"
    assert profile.address_for("001").street == "CALLE FICTICIA"


def test_department_description_is_taken_from_the_official_catalog() -> None:
    profile = fictional_fiscal_profile()
    address = replace(profile.address, department_code=12, department_description="")

    normalized = normalize_fiscal_profile(replace(profile, address=address))

    assert normalized.address.department_description == "CENTRAL"


def test_department_description_is_compared_ignoring_case() -> None:
    profile = fictional_fiscal_profile()
    address = replace(profile.address, department_description=" capital ")

    normalized = normalize_fiscal_profile(replace(profile, address=address))

    assert normalized.address.department_description == "CAPITAL"


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"department_code": 21}, "domicilio.departamento"),
        ({"department_description": "CENTRAL"}, "domicilio.descripcion_departamento"),
        ({"district_code": 5}, "domicilio.distrito"),
        ({"district_description": "SOLO DESCRIPCION"}, "domicilio.distrito"),
    ],
)
def test_address_inconsistent_with_the_catalog_is_rejected(
    changes: dict, field: str
) -> None:
    profile = fictional_fiscal_profile()
    address = replace(profile.address, **changes)

    with pytest.raises(UnprocessableEntityError) as raised:
        normalize_fiscal_profile(replace(profile, address=address))

    assert raised.value.code == "emitters.fiscal_profile_invalid"
    assert raised.value.details["field"] == field


def test_profile_needs_between_one_and_nine_activities() -> None:
    profile = fictional_fiscal_profile()
    too_many = tuple(EconomicActivity(code=str(i), description="X") for i in range(10))

    for activities in ((), too_many):
        with pytest.raises(UnprocessableEntityError):
            normalize_fiscal_profile(replace(profile, activities=activities))


def test_establishment_codes_have_three_digits() -> None:
    profile = fictional_fiscal_profile()

    with pytest.raises(UnprocessableEntityError):
        normalize_fiscal_profile(
            replace(profile, establishments={"2": profile.address})
        )


@pytest.mark.parametrize(
    "changes", [{"taxpayer_type": 3}, {"regime_type": 0}, {"regime_type": 9}]
)
def test_taxpayer_and_regime_types_follow_the_xsd(changes: dict) -> None:
    with pytest.raises(UnprocessableEntityError):
        normalize_fiscal_profile(replace(fictional_fiscal_profile(), **changes))
