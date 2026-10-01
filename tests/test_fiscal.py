from datetime import date, datetime

import pytest

from kilasifen.engine.sdk.fiscal import (
    build_qr_payload,
    build_qr_payload_from_signed_xml,
    calculate_mod11_dv,
    format_cdc_for_kude,
    generate_cdc,
    generate_dcarqr,
    generate_dcarqr_from_signed_xml,
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


def test_build_qr_payload_matches_manual_v150_example():
    payload = build_qr_payload(
        cdc="01444444017001001001452822017012515873260988",
        d_fe_emi_de="2017-01-25T09:35:17",
        digest_value="yzGYhUx1/XYYzksWB+fPR3Qc50c=",
        id_csc="0001",
        csc="ABCD0000000000000000000000000000",
        d_ruc_rec="88899990",
        d_tot_gral_ope="300000",
        d_tot_iva="27272",
        c_items=2,
        environment="production",
    )

    assert payload["c_hash_qr"] == (
        "40589613f88eb38dc7ee5e89b1e79ff0"
        "0cc3107e432cca0c759d1a6062e4a72c"
    )
    assert payload["url"] == (
        "https://ekuatia.set.gov.py/consultas/qr?"
        "nVersion=150"
        "&Id=01444444017001001001452822017012515873260988"
        "&dFeEmiDE=323031372d30312d32355430393a33353a3137"
        "&dRucRec=88899990"
        "&dTotGralOpe=300000.00000000"
        "&dTotIVA=27272.00000000"
        "&cItems=2"
        "&DigestValue=797a4759685578312f5859597a6b7357422b6650523351633530633d"
        "&IdCSC=0001"
        "&cHashQR="
        "40589613f88eb38dc7ee5e89b1e79ff0"
        "0cc3107e432cca0c759d1a6062e4a72c"
    )


def test_generate_dcarqr_xml_escaped():
    dcarqr = generate_dcarqr(
        cdc="01444444017001001001452822017012515873260988",
        d_fe_emi_de="2017-01-25T09:35:17",
        digest_value="yzGYhUx1/XYYzksWB+fPR3Qc50c=",
        id_csc="0001",
        csc="ABCD0000000000000000000000000000",
        d_ruc_rec="88899990",
        d_tot_gral_ope="300000",
        d_tot_iva="27272",
        c_items=2,
        xml_escaped=True,
    )
    assert "&amp;" in dcarqr
    assert "&cHashQR=" not in dcarqr


def test_build_qr_payload_uses_default_zero_values():
    payload = build_qr_payload(
        cdc="01444444017001001001452822017012515873260988",
        d_fe_emi_de="2017-01-25",
        digest_value="abc123=",
        id_csc=1,
        csc="ABCD0000000000000000000000000000",
        d_num_id_rec=None,
        d_tot_gral_ope=None,
        d_tot_iva=None,
        c_items=None,
        environment="test",
    )

    assert "&dRucRec=0" in payload["step1"]
    assert "&dTotGralOpe=0.00000000" in payload["step1"]
    assert "&dTotIVA=0.00000000" in payload["step1"]
    assert "&cItems=0" in payload["step1"]
    assert payload["url"].startswith(
        "https://ekuatia.set.gov.py/consultas-test/qr?"
    )


def test_build_qr_payload_rejects_both_receptor_identifiers():
    with pytest.raises(ValueError, match="either d_ruc_rec or d_num_id_rec"):
        build_qr_payload(
            cdc="01444444017001001001452822017012515873260988",
            d_fe_emi_de="2017-01-25T09:35:17",
            digest_value="yzGYhUx1/XYYzksWB+fPR3Qc50c=",
            id_csc="0001",
            csc="ABCD0000000000000000000000000000",
            d_ruc_rec="88899990",
            d_num_id_rec="1234567",
        )


def test_build_qr_payload_from_signed_xml_uses_literal_totals():
    signed_xml = """
<rDE xmlns="http://ekuatia.set.gov.py/sifen/xsd">
  <dVerFor>150</dVerFor>
  <DE Id="01800241355001001000075122026042411234567890">
    <gTimb><iTiDE>1</iTiDE></gTimb>
    <gDatGralOpe>
      <dFeEmiDE>2026-04-24T09:55:00</dFeEmiDE>
      <gOpeCom><iTImp>1</iTImp></gOpeCom>
      <gDatRec><iNatRec>1</iNatRec><dRucRec>80069563</dRucRec></gDatRec>
    </gDatGralOpe>
    <gDtipDE><gCamItem/><gCamItem/></gDtipDE>
    <gTotSub>
      <dTotGralOpe>110000.00</dTotGralOpe>
      <dTotIVA>10000.00</dTotIVA>
    </gTotSub>
  </DE>
  <Signature xmlns="http://www.w3.org/2000/09/xmldsig#">
    <SignedInfo>
      <Reference URI="#01800241355001001000075122026042411234567890">
        <DigestValue>B7+e93lmdfIpt96amatjsp7YyStylWGyREb4GtutGAE=</DigestValue>
      </Reference>
    </SignedInfo>
  </Signature>
</rDE>
"""
    payload = build_qr_payload_from_signed_xml(
        signed_xml=signed_xml,
        id_csc="0001",
        csc="ABCD0000000000000000000000000000",
        environment="test",
    )
    assert "&dRucRec=80069563" in payload["step1"]
    assert "&dTotGralOpe=110000.00" in payload["step1"]
    assert "&dTotIVA=10000.00" in payload["step1"]
    assert "&cItems=2" in payload["step1"]
    assert payload["url"].startswith(
        "https://ekuatia.set.gov.py/consultas-test/qr?"
    )


def test_generate_dcarqr_from_signed_xml_uses_remision_zero_totals():
    signed_xml = """
<rDE xmlns="http://ekuatia.set.gov.py/sifen/xsd">
  <dVerFor>150</dVerFor>
  <DE Id="01800241355001001000075222026042411234567898">
    <gTimb><iTiDE>7</iTiDE></gTimb>
    <gDatGralOpe>
      <dFeEmiDE>2026-04-24T09:56:00</dFeEmiDE>
      <gOpeCom><iTImp>1</iTImp></gOpeCom>
      <gDatRec><iNatRec>2</iNatRec></gDatRec>
    </gDatGralOpe>
    <gDtipDE><gCamItem/></gDtipDE>
    <gTotSub>
      <dTotGralOpe>999999.99</dTotGralOpe>
      <dTotIVA>777.77</dTotIVA>
    </gTotSub>
  </DE>
  <Signature xmlns="http://www.w3.org/2000/09/xmldsig#">
    <SignedInfo>
      <Reference URI="#01800241355001001000075222026042411234567898">
        <DigestValue>B7+e93lmdfIpt96amatjsp7YyStylWGyREb4GtutGAE=</DigestValue>
      </Reference>
    </SignedInfo>
  </Signature>
</rDE>
"""
    url = generate_dcarqr_from_signed_xml(
        signed_xml=signed_xml,
        id_csc="0001",
        csc="ABCD0000000000000000000000000000",
        environment="test",
    )
    assert "&dNumIDRec=0" in url
    assert "&dTotGralOpe=0" in url
    assert "&dTotIVA=0" in url
