from datetime import date, datetime

import pytest

from pysifen.sdk.fiscal import (
    calculate_mod11_dv,
    format_cdc_for_kude,
    generate_cdc,
)


def test_calculate_mod11_dv_matches_official_example():
    base = "0144444401700100100145282201701251587326098"
    assert calculate_mod11_dv(base) == 8


def test_calculate_mod11_dv_handles_alphanumeric_input():
    assert calculate_mod11_dv("123A", base_max=11) == 0


def test_generate_cdc_matches_manual_v150_example():
    cdc = generate_cdc(
        i_tide=1,
        d_ruc_em="44444401",
        d_dv_emi=7,
        d_est="001",
        d_pun_exp="001",
        d_num_doc="14528",
        i_tip_cont=2,
        d_fe_emi_de="2017-01-25T15:58:17",
        i_tip_emi=1,
        d_cod_seg="587326098",
    )
    assert cdc == "01444444017001001001452822017012515873260988"
    assert len(cdc) == 44


def test_generate_cdc_accepts_date_objects():
    cdc = generate_cdc(
        i_tide=1,
        d_ruc_em="12345",
        d_dv_emi=9,
        d_est=1,
        d_pun_exp=2,
        d_num_doc=3,
        i_tip_cont=1,
        d_fe_emi_de=date(2026, 4, 22),
        i_tip_emi=1,
        d_cod_seg=987654321,
    )
    assert len(cdc) == 44
    assert cdc[25:33] == "20260422"


def test_generate_cdc_accepts_datetime_objects():
    cdc = generate_cdc(
        i_tide=7,
        d_ruc_em="7654321A",
        d_dv_emi=5,
        d_est=1,
        d_pun_exp=1,
        d_num_doc=456,
        i_tip_cont=2,
        d_fe_emi_de=datetime(2025, 3, 15, 10, 20, 30),
        i_tip_emi=2,
        d_cod_seg=123456789,
    )
    assert len(cdc) == 44
    assert cdc[0:2] == "07"
    assert cdc[2:10] == "7654321A"
    assert cdc[25:33] == "20250315"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        (
            {"d_ruc_em": "123-4"},
            "must not include DV separator",
        ),
        (
            {"d_ruc_em": "12A34"},
            "only as the last character",
        ),
        (
            {"d_cod_seg": "000000123", "d_num_doc": "123"},
            "must be different from d_num_doc",
        ),
        (
            {"i_tip_cont": 3},
            "must be <= 2",
        ),
        (
            {"d_fe_emi_de": "2026/04/22"},
            "must be date-like",
        ),
    ],
)
def test_generate_cdc_validates_input(kwargs, message):
    base_kwargs = {
        "i_tide": 1,
        "d_ruc_em": "1234567",
        "d_dv_emi": 1,
        "d_est": 1,
        "d_pun_exp": 1,
        "d_num_doc": 1,
        "i_tip_cont": 1,
        "d_fe_emi_de": "2026-04-22",
        "i_tip_emi": 1,
        "d_cod_seg": 987654321,
    }
    base_kwargs.update(kwargs)

    with pytest.raises(ValueError, match=message):
        generate_cdc(**base_kwargs)


def test_format_cdc_for_kude_groups_by_four():
    cdc = "01444444017001001001452822017012515873260988"
    assert format_cdc_for_kude(cdc) == (
        "0144 4444 0170 0100 1001 4528 2201 7012 5158 7326 0988"
    )
