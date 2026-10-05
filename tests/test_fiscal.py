from datetime import date, datetime
from decimal import Decimal

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




# ---------------------------------------------------------------------------
# Codigo QR (MT v150 §13.8; NT 10 §3 y §4; NT 23 §1.1)
# ---------------------------------------------------------------------------

# Ejemplo oficial de MT v150 §13.8.4 (pags. 207-208). El "nVersion=142" de la
# pag. 208 es una errata: el hash oficial solo se reproduce con 150.
_MT_CDC = "01444444017001001001452822017012515873260988"
_MT_FECHA = "2017-01-25T09:35:17"
_MT_DIGEST = "yzGYhUx1/XYYzksWB+fPR3Qc50c="
_MT_CSC = "ABCD0000000000000000000000000000"
_MT_HASH = "97ddbb3c1e7d65af03a70ffe21f2b34846ab1c89e0566c35222086766b7374ed"
_MT_STEP1 = (
    "nVersion=150"
    "&Id=01444444017001001001452822017012515873260988"
    "&dFeEmiDE=323031372d30312d32355430393a33353a3137"
    "&dRucRec=88899990"
    "&dTotGralOpe=300000"
    "&dTotIVA=27272"
    "&cItems=2"
    "&DigestValue=797a4759685578312f5859597a6b7357422b6650523351633530633d"
    "&IdCSC=0001"
)
_MT_URL = f"https://ekuatia.set.gov.py/consultas/qr?{_MT_STEP1}&cHashQR={_MT_HASH}"


def _mt_payload(**overrides):
    kwargs = {
        "cdc": _MT_CDC,
        "d_fe_emi_de": _MT_FECHA,
        "digest_value": _MT_DIGEST,
        "id_csc": "0001",
        "csc": _MT_CSC,
        "d_ruc_rec": "88899990",
        "d_tot_gral_ope": "300000",
        "d_tot_iva": "27272",
        "c_items": 2,
        "environment": "production",
    }
    kwargs.update(overrides)
    return build_qr_payload(**kwargs)


def test_build_qr_payload_matches_manual_v150_example():
    payload = _mt_payload()

    assert payload["step1"] == _MT_STEP1
    assert payload["c_hash_qr"] == _MT_HASH
    assert payload["url"] == _MT_URL


def test_build_qr_payload_accepts_int_and_decimal_literals():
    payload = _mt_payload(d_tot_gral_ope=Decimal("300000"), d_tot_iva=27272)

    assert payload["c_hash_qr"] == _MT_HASH


def test_build_qr_payload_pads_id_csc_to_four_digits():
    assert _mt_payload(id_csc=1)["url"] == _MT_URL


def test_build_qr_payload_accepts_a_datetime_for_d002():
    payload = _mt_payload(d_fe_emi_de=datetime(2017, 1, 25, 9, 35, 17))

    assert payload["c_hash_qr"] == _MT_HASH


def test_build_qr_payload_keeps_the_amount_literal():
    payload = _mt_payload(d_tot_gral_ope="110000.00", d_tot_iva="10000.5")

    assert "&dTotGralOpe=110000.00&dTotIVA=10000.5&" in payload["step1"]


def test_build_qr_payload_writes_zero_for_values_the_de_does_not_carry():
    payload = _mt_payload(
        d_ruc_rec=None,
        d_num_id_rec="0",
        d_tot_gral_ope=None,
        d_tot_iva="",
        c_items=None,
        environment="test",
    )

    # Un no contribuyente sin D210 (B2F tras la NT 23) o innominado va con
    # dNumIDRec=0, y los montos ausentes con 0 (nota (*) de §13.8.2).
    assert "&dNumIDRec=0&dTotGralOpe=0&dTotIVA=0&cItems=0&" in payload["step1"]
    assert payload["url"].startswith("https://ekuatia.set.gov.py/consultas-test/qr?")


@pytest.mark.parametrize("vacio", [None, "", "  "])
def test_build_qr_payload_requires_the_receptor(vacio):
    # Suponer el receptor daria un QR distinto del XML (validacion 2500):
    # quien olvida D206 recibe un error local, no un dNumIDRec=0.
    with pytest.raises(ValueError, match="d_ruc_rec .* or d_num_id_rec"):
        _mt_payload(d_ruc_rec=vacio, d_num_id_rec=vacio)


def test_generate_dcarqr_requires_the_receptor():
    with pytest.raises(ValueError, match="d_ruc_rec .* or d_num_id_rec"):
        generate_dcarqr(
            cdc=_MT_CDC,
            d_fe_emi_de=_MT_FECHA,
            digest_value=_MT_DIGEST,
            id_csc="0001",
            csc=_MT_CSC,
            d_tot_gral_ope="300000",
            d_tot_iva="27272",
            c_items=2,
        )


def test_build_qr_payload_names_the_d210_parameter_dnumidrec():
    payload = _mt_payload(d_ruc_rec=None, d_num_id_rec="4512369")

    assert "&dNumIDRec=4512369&" in payload["step1"]
    assert "dRucRec" not in payload["url"]


def test_build_qr_payload_rejects_both_receptor_identifiers():
    with pytest.raises(ValueError, match="either d_ruc_rec or d_num_id_rec"):
        _mt_payload(d_num_id_rec="1234567")


@pytest.mark.parametrize("ruc", ["80069563-1", "01234567", "12", "123456789"])
def test_build_qr_payload_rejects_a_d206_outside_truc(ruc):
    with pytest.raises(ValueError, match="D206"):
        _mt_payload(d_ruc_rec=ruc)


@pytest.mark.parametrize("fecha", ["2017-01-25", date(2017, 1, 25), "20170125"])
def test_build_qr_payload_rejects_d002_without_time(fecha):
    with pytest.raises(ValueError, match="D002"):
        _mt_payload(d_fe_emi_de=fecha)


@pytest.mark.parametrize("monto", [300000.0, "-1", "1e5", "300.000,00", True])
def test_build_qr_payload_rejects_amounts_that_are_not_xml_literals(monto):
    with pytest.raises(ValueError, match="d_tot_gral_ope"):
        _mt_payload(d_tot_gral_ope=monto)


@pytest.mark.parametrize(
    "csc", ["ABCD000000000000000000000000000", "ABCD00000000000000000000000000-0"]
)
def test_build_qr_payload_rejects_a_csc_that_is_not_32_alphanumerics(csc):
    with pytest.raises(ValueError, match="32 alphanumeric"):
        _mt_payload(csc=csc)


@pytest.mark.parametrize("id_csc", ["0", "10000", "A1"])
def test_build_qr_payload_rejects_an_id_csc_outside_1_9999(id_csc):
    with pytest.raises(ValueError, match="id_csc"):
        _mt_payload(id_csc=id_csc)


def test_build_qr_payload_never_returns_the_csc():
    payload = _mt_payload()

    assert set(payload) == {"step1", "c_hash_qr", "url", "dcarqr_xml"}
    assert all(_MT_CSC not in value for value in payload.values())


def test_build_qr_payload_checks_the_dcarqr_length():
    with pytest.raises(ValueError, match="between 100 and 600"):
        _mt_payload(digest_value="A" * 300)


def test_generate_dcarqr_xml_escaped():
    dcarqr = generate_dcarqr(
        cdc=_MT_CDC,
        d_fe_emi_de=_MT_FECHA,
        digest_value=_MT_DIGEST,
        id_csc="0001",
        csc=_MT_CSC,
        d_ruc_rec="88899990",
        d_tot_gral_ope="300000",
        d_tot_iva="27272",
        c_items=2,
        xml_escaped=True,
    )
    assert dcarqr == _MT_URL.replace("&", "&amp;")


def _signed_rde(
    *,
    receptor: str = "<iNatRec>1</iNatRec><dRucRec>88899990</dRucRec>",
    totales: str | None = (
        "<dTotGralOpe>300000</dTotGralOpe><dTotIVA>27272</dTotIVA>"
    ),
    items: int = 2,
    digest: str | None = _MT_DIGEST,
) -> str:
    """rDE firmado minimo con los valores que lee el QR."""

    gtotsub = f"<gTotSub>{totales}</gTotSub>" if totales is not None else ""
    signed_info = (
        f'<SignedInfo><Reference URI="#{_MT_CDC}">'
        f"<DigestValue>{digest}</DigestValue></Reference></SignedInfo>"
        if digest is not None
        else "<SignedInfo/>"
    )
    return (
        '<rDE xmlns="http://ekuatia.set.gov.py/sifen/xsd">'
        "<dVerFor>150</dVerFor>"
        f'<DE Id="{_MT_CDC}">'
        "<gTimb><iTiDE>1</iTiDE></gTimb>"
        f"<gDatGralOpe><dFeEmiDE>{_MT_FECHA}</dFeEmiDE>"
        "<gOpeCom><iTImp>1</iTImp></gOpeCom>"
        f"<gDatRec>{receptor}</gDatRec></gDatGralOpe>"
        f"<gDtipDE>{'<gCamItem/>' * items}</gDtipDE>"
        f"{gtotsub}"
        "</DE>"
        '<Signature xmlns="http://www.w3.org/2000/09/xmldsig#">'
        f"{signed_info}</Signature>"
        "</rDE>"
    )


def _qr_from_xml(signed_xml: str, **kwargs):
    return build_qr_payload_from_signed_xml(
        signed_xml=signed_xml, id_csc="0001", csc=_MT_CSC, **kwargs
    )


def test_build_qr_payload_from_signed_xml_matches_manual_v150_example():
    payload = _qr_from_xml(_signed_rde())

    assert payload["url"] == _MT_URL


def test_build_qr_payload_from_signed_xml_uses_literal_totals():
    payload = _qr_from_xml(
        _signed_rde(
            totales="<dTotGralOpe>110000.00</dTotGralOpe><dTotIVA>10000.00</dTotIVA>"
        ),
        environment="test",
    )

    assert "&dTotGralOpe=110000.00&dTotIVA=10000.00&cItems=2&" in payload["step1"]
    assert payload["url"].startswith("https://ekuatia.set.gov.py/consultas-test/qr?")


@pytest.mark.parametrize(
    ("receptor", "parametro"),
    [
        (
            "<iNatRec>2</iNatRec><iTipIDRec>1</iTipIDRec>"
            "<dNumIDRec>4512369</dNumIDRec>",
            "&dNumIDRec=4512369&",
        ),
        # Innominado (NT 23 §1.1: D210 = 0).
        (
            "<iNatRec>2</iNatRec><iTipIDRec>5</iTipIDRec><dNumIDRec>0</dNumIDRec>",
            "&dNumIDRec=0&",
        ),
        # B2F sin D210 (opcional desde la NT 23): nota (*) de §13.8.2.
        ("<iNatRec>2</iNatRec>", "&dNumIDRec=0&"),
    ],
)
def test_build_qr_payload_from_signed_xml_uses_d210_for_non_taxpayers(
    receptor, parametro
):
    payload = _qr_from_xml(_signed_rde(receptor=receptor))

    assert parametro in payload["step1"]
    assert "dRucRec" not in payload["url"]


def test_build_qr_payload_from_signed_xml_writes_zero_without_gtotsub():
    # Nota de remision: F001 no se informa si C002=7 (MT v150 p. 102).
    payload = _qr_from_xml(_signed_rde(totales=None, items=1))

    assert "&dTotGralOpe=0&dTotIVA=0&cItems=1&" in payload["step1"]


def test_build_qr_payload_from_signed_xml_writes_zero_without_f017():
    # Autofactura o DE sin IVA con iTImp 1: F017 es 0-1 (MT v150 pp. 102 y
    # 105, validacion 2370) y el QR lleva 0 (NT 10 §4, obs. 1).
    payload = _qr_from_xml(_signed_rde(totales="<dTotGralOpe>573000</dTotGralOpe>"))

    assert "&dTotGralOpe=573000&dTotIVA=0&" in payload["step1"]


def test_build_qr_payload_from_signed_xml_takes_nversion_from_dverfor():
    with pytest.raises(ValueError, match="dVerFor"):
        _qr_from_xml(_signed_rde(), qr_version=142)
    assert _qr_from_xml(_signed_rde(), qr_version="150")["url"] == _MT_URL


def test_build_qr_payload_from_signed_xml_requires_the_signature_digest():
    with pytest.raises(ValueError, match="DigestValue"):
        _qr_from_xml(_signed_rde(digest=None))


def test_build_qr_payload_from_signed_xml_rejects_a_taxpayer_without_d206():
    with pytest.raises(ValueError, match="dRucRec"):
        _qr_from_xml(_signed_rde(receptor="<iNatRec>1</iNatRec>"))


def test_generate_dcarqr_from_signed_xml_never_returns_the_csc():
    url = generate_dcarqr_from_signed_xml(
        signed_xml=_signed_rde().encode("utf-8"),
        id_csc=1,
        csc=_MT_CSC,
        xml_escaped=True,
    )

    assert url == _MT_URL.replace("&", "&amp;")
    assert _MT_CSC not in url
