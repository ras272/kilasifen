"""Tests for the platform QR: injection into the signed XML and its image."""

from dataclasses import replace
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from PIL import Image, ImageOps

from kilasifen.domain.emitters.models import Emitter
from kilasifen.engine.sdk.errors import SifenValidationError
from kilasifen.engine.sdk.fiscal import build_qr_payload_from_signed_xml
from kilasifen.infrastructure.kude.qr_generator import (
    MIN_QUIET_ZONE_MODULES,
    quiet_zone_modules,
    render_qr_image,
)
from kilasifen.infrastructure.kude.xml_qr_injector import (
    apply_real_qr_to_signed_xml,
    compute_qr_url_from_signed_xml,
)

_GOLDEN_DIR = Path(__file__).resolve().parents[1] / "golden"
_NS = {"s": "http://ekuatia.set.gov.py/sifen/xsd"}
_CSC = "ABCD0000000000000000000000000000"


def _emitter(**overrides) -> Emitter:
    ts = datetime.now(timezone.utc)
    emitter = Emitter(
        id="emitter-1",
        external_id="erp-test",
        ruc="80024135",
        dv="5",
        legal_name="ARES PARAGUAY SRL",
        tax_environment="test",
        status="active",
        csc=_CSC,
        csc_id="0001",
        created_at=ts,
        updated_at=ts,
    )
    return replace(emitter, **overrides)


def _golden(name: str) -> str:
    return (_GOLDEN_DIR / f"{name}.xml").read_text(encoding="utf-8")


def _dcarqr(signed_xml: str) -> str:
    return ET.fromstring(signed_xml).findtext("s:gCamFuFD/s:dCarQR", namespaces=_NS)


def test_injected_qr_is_the_engine_qr_of_the_signed_xml():
    signed_xml = _golden("factura_b2b_iva10")

    injected = apply_real_qr_to_signed_xml(signed_xml, emitter=_emitter())

    expected = build_qr_payload_from_signed_xml(
        signed_xml=signed_xml, id_csc="0001", csc=_CSC, environment="test"
    )["url"]
    assert _dcarqr(injected) == expected
    assert "&dRucRec=80069563&" in expected


def test_injected_qr_names_the_receptor_of_a_non_taxpayer_dnumidrec():
    # MT v150 §13.8.2 (D206 o D210) y NT 23 §1.1: innominado con D210 = 0.
    signed_xml = _golden("factura_b2c_iva_mixto")
    assert "<iNatRec>2</iNatRec>" in signed_xml

    url = _dcarqr(apply_real_qr_to_signed_xml(signed_xml, emitter=_emitter()))

    assert "&dNumIDRec=0&" in url
    assert "dRucRec" not in url


def test_injected_qr_escapes_ampersands_once_and_keeps_the_signature():
    signed_xml = _golden("factura_b2b_iva10")

    injected = apply_real_qr_to_signed_xml(signed_xml, emitter=_emitter())

    assert "&amp;amp;" not in injected
    assert injected.split("<gCamFuFD>")[0] == signed_xml.split("<gCamFuFD>")[0]


def test_injected_qr_never_contains_the_csc():
    injected = apply_real_qr_to_signed_xml(
        _golden("factura_b2b_iva10"), emitter=_emitter()
    )

    assert _CSC not in injected


def test_injected_qr_uses_the_production_url_for_production_emitters():
    url = compute_qr_url_from_signed_xml(
        _golden("factura_b2b_iva10"), emitter=_emitter(tax_environment="production")
    )

    assert url.startswith("https://ekuatia.set.gov.py/consultas/qr?")


def test_injected_qr_writes_a_legacy_short_id_csc_with_four_digits():
    url = compute_qr_url_from_signed_xml(
        _golden("factura_b2b_iva10"), emitter=_emitter(csc_id="1")
    )

    assert "&IdCSC=0001&" in url


@pytest.mark.parametrize("missing", ["csc", "csc_id"])
def test_injected_qr_requires_the_emitter_csc(missing):
    with pytest.raises(SifenValidationError, match="emitters.csc_required"):
        apply_real_qr_to_signed_xml(
            _golden("factura_b2b_iva10"), emitter=_emitter(**{missing: None})
        )


def test_invalid_qr_values_become_a_validation_error_without_the_csc():
    with pytest.raises(SifenValidationError) as excinfo:
        compute_qr_url_from_signed_xml(
            _golden("factura_b2b_iva10"), emitter=_emitter(csc="short-csc")
        )

    assert str(excinfo.value).startswith("documents.qr.invalid")
    assert "short-csc" not in str(excinfo.value)


def test_injection_requires_the_dcarqr_element():
    signed_xml = _golden("factura_b2b_iva10")
    without_qr = signed_xml.split("<gCamFuFD>")[0] + "</rDE>"

    with pytest.raises(SifenValidationError, match="dcarqr_element_missing"):
        apply_real_qr_to_signed_xml(without_qr, emitter=_emitter())


def test_render_qr_image_returns_png_bytes():
    png = render_qr_image("https://ekuatia.set.gov.py/consultas-test/qr?x=1")
    assert png[:4] == b"\x89PNG"
    assert len(png) > 100


@pytest.mark.parametrize(
    "url",
    [
        "https://ekuatia.set.gov.py/consultas-test/qr?x=1",
        # A real dCarQR: QR version 14 or more.
        _dcarqr(_golden("factura_b2c_iva_mixto")),
    ],
)
def test_render_qr_image_leaves_a_quiet_zone_of_at_least_four_modules(url):
    box_size = 4
    image = Image.open(BytesIO(render_qr_image(url, box_size=box_size))).convert("L")

    left, top, right, bottom = ImageOps.invert(image).getbbox()
    margins = (left, top, image.width - right, image.height - bottom)
    # ISO/IEC 18004: four modules; MT v150 §13.8.1: 10% of the width in all.
    assert min(margins) >= MIN_QUIET_ZONE_MODULES * box_size
    assert (margins[0] + margins[2]) / image.width >= 0.10


@pytest.mark.parametrize(
    ("modules", "quiet_zone"), [(21, 4), (72, 4), (73, 5), (177, 10)]
)
def test_quiet_zone_grows_to_ten_percent_of_the_width(modules, quiet_zone):
    assert quiet_zone_modules(modules) == quiet_zone
    assert 2 * quiet_zone / (modules + 2 * quiet_zone) >= 0.10
