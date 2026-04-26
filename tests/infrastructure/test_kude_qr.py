"""Tests for SIFEN QR URL generator (Manual section 13.8)."""

from datetime import datetime
from decimal import Decimal

import pytest

from kilasifen.infrastructure.kude.qr_generator import (
    build_sifen_qr_url,
    render_qr_image,
)


# Values from Manual Tecnico v150 section 13.8.4 example.
# Note: the manual table on line ~9812 shows nVersion=142 due to a typo;
# the rest of the manual (and the project decision) uses 150.
_MANUAL_CDC = "01444444017001001001452822017012515873260988"
_MANUAL_FECHA = datetime(2017, 1, 25, 9, 35, 17)
_MANUAL_RUC = "88899990"
_MANUAL_TOTAL = Decimal("300000")
_MANUAL_TOTAL_IVA = Decimal("27272")
_MANUAL_ITEMS = 2
_MANUAL_DIGEST = "yzGYhUx1/XYYzksWB+fPR3Qc50c="
_MANUAL_CSC = "ABCD0000000000000000000000000000"
_MANUAL_ID_CSC = "0001"
_MANUAL_HASH = (
    "97ddbb3c1e7d65af03a70ffe21f2b34846ab1c89e0566c35222086766b7374ed"
)
_MANUAL_DATA_PARAMS = (
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


def test_build_sifen_qr_url_matches_manual_example_byte_exact():
    url = build_sifen_qr_url(
        cdc=_MANUAL_CDC,
        fecha_emision=_MANUAL_FECHA,
        rec_identifier=_MANUAL_RUC,
        total_general=_MANUAL_TOTAL,
        total_iva=_MANUAL_TOTAL_IVA,
        cantidad_items=_MANUAL_ITEMS,
        digest_value=_MANUAL_DIGEST,
        csc=_MANUAL_CSC,
        id_csc=_MANUAL_ID_CSC,
        ambiente="produccion",
    )

    expected = (
        "https://ekuatia.set.gov.py/consultas/qr?"
        + _MANUAL_DATA_PARAMS
        + f"&cHashQR={_MANUAL_HASH}"
    )
    assert url == expected


def test_build_sifen_qr_url_does_not_include_csc():
    url = build_sifen_qr_url(
        cdc=_MANUAL_CDC,
        fecha_emision=_MANUAL_FECHA,
        rec_identifier=_MANUAL_RUC,
        total_general=_MANUAL_TOTAL,
        total_iva=_MANUAL_TOTAL_IVA,
        cantidad_items=_MANUAL_ITEMS,
        digest_value=_MANUAL_DIGEST,
        csc=_MANUAL_CSC,
        id_csc=_MANUAL_ID_CSC,
        ambiente="produccion",
    )

    assert _MANUAL_CSC not in url


def test_build_sifen_qr_url_uses_test_base_url_for_test_ambiente():
    url = build_sifen_qr_url(
        cdc=_MANUAL_CDC,
        fecha_emision=_MANUAL_FECHA,
        rec_identifier=_MANUAL_RUC,
        total_general=_MANUAL_TOTAL,
        total_iva=_MANUAL_TOTAL_IVA,
        cantidad_items=_MANUAL_ITEMS,
        digest_value=_MANUAL_DIGEST,
        csc=_MANUAL_CSC,
        id_csc=_MANUAL_ID_CSC,
        ambiente="test",
    )

    assert url.startswith("https://ekuatia.set.gov.py/consultas-test/qr?")


def test_build_sifen_qr_url_treats_zero_amounts_as_literal_zero():
    url = build_sifen_qr_url(
        cdc=_MANUAL_CDC,
        fecha_emision=_MANUAL_FECHA,
        rec_identifier=_MANUAL_RUC,
        total_general=Decimal("0"),
        total_iva=None,
        cantidad_items=1,
        digest_value=_MANUAL_DIGEST,
        csc=_MANUAL_CSC,
        id_csc=_MANUAL_ID_CSC,
        ambiente="test",
    )

    assert "&dTotGralOpe=0&" in url
    assert "&dTotIVA=0&" in url


def test_build_sifen_qr_url_rejects_unknown_ambiente():
    with pytest.raises(ValueError):
        build_sifen_qr_url(
            cdc=_MANUAL_CDC,
            fecha_emision=_MANUAL_FECHA,
            rec_identifier=_MANUAL_RUC,
            total_general=_MANUAL_TOTAL,
            total_iva=_MANUAL_TOTAL_IVA,
            cantidad_items=_MANUAL_ITEMS,
            digest_value=_MANUAL_DIGEST,
            csc=_MANUAL_CSC,
            id_csc=_MANUAL_ID_CSC,
            ambiente="staging",
        )


def test_render_qr_image_returns_png_bytes():
    png = render_qr_image("https://ekuatia.set.gov.py/consultas-test/qr?x=1")
    assert png[:4] == b"\x89PNG"
    assert len(png) > 100
