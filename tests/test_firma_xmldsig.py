"""Firma XMLDSig de documentos del SIFEN con el certificado de prueba."""
import os

import pytest

pytest.importorskip("signxml", reason="signxml not installed")
pytest.importorskip("cryptography", reason="cryptography not installed")

SAMPLES_DIR = os.path.join(
    os.path.dirname(__file__), "..", "kilasifen", "engine", "de", "samples", "v150"
)


@pytest.fixture
def cert_path():
    return os.path.join(os.path.dirname(__file__), "test_cert.pfx")


@pytest.fixture
def cert_data(cert_path):
    if not os.path.exists(cert_path):
        pytest.skip("test_cert.pfx not found")
    with open(cert_path, "rb") as f:
        return f.read()


@pytest.fixture
def sample_xml():
    path = os.path.join(SAMPLES_DIR, "factura_electronica.xml")
    with open(path) as f:
        return f.read()


@pytest.fixture
def sample_rde():
    from kilasifen.engine.de.bindings.v150.fe_v141 import RDe

    path = os.path.join(SAMPLES_DIR, "factura_electronica.xml")
    return RDe.from_path(path)


class TestSignXml:
    """Firma XML con signxml a traves de kilasifen.engine.firma."""

    def test_reuses_pkcs12_parsing_for_repeated_signatures(
        self, cert_data, sample_rde, monkeypatch
    ):
        """Reutiliza el PKCS12 ya decodificado en firmas repetidas."""
        from cryptography.hazmat.primitives.serialization import pkcs12

        from kilasifen.engine.firma import sign_xml
        from kilasifen.engine.sdk import signer as signer_module

        signer_module.clear_pkcs12_signer_cache()

        calls = []
        original_loader = pkcs12.load_key_and_certificates

        def wrapped_loader(*args, **kwargs):
            calls.append(1)
            return original_loader(*args, **kwargs)

        monkeypatch.setattr(
            "cryptography.hazmat.primitives.serialization.pkcs12.load_key_and_certificates",
            wrapped_loader,
        )

        xml = sample_rde.to_xml()
        doc_id = sample_rde.DE.Id

        first = sign_xml(xml, cert_data, "test1234", doc_id)
        second = sign_xml(xml, cert_data, "test1234", doc_id)

        assert "SignatureValue" in first
        assert second == first
        assert len(calls) == 1

    def test_sign_xml_with_test_cert(
        self, cert_data, sample_rde
    ):
        """Firma el XML de ejemplo y verifica el nodo Signature."""
        from kilasifen.engine.firma import sign_xml

        xml = sample_rde.to_xml()
        signed = sign_xml(
            xml, cert_data, "test1234", sample_rde.DE.Id
        )

        assert "<ds:Signature" in signed or "<Signature" in signed
        assert "SignatureValue" in signed
        assert "SignedInfo" in signed

    def test_sign_xml_removes_existing_signature(
        self, cert_data, sample_rde
    ):
        from lxml import etree

        from kilasifen.engine.firma import sign_xml

        xml = sample_rde.to_xml()
        signed = sign_xml(xml, cert_data, "test1234", sample_rde.DE.Id)
        root = etree.fromstring(signed.encode())
        ns = {"ds": "http://www.w3.org/2000/09/xmldsig#"}

        assert len(root.findall(".//ds:Signature", ns)) == 1

    def test_sign_xml_sha256(self, cert_data, sample_rde):
        """Verifica que usa SHA256 (no SHA1)."""
        from kilasifen.engine.firma import sign_xml

        xml = sample_rde.to_xml()
        signed = sign_xml(
            xml, cert_data, "test1234", sample_rde.DE.Id
        )

        assert "rsa-sha256" in signed or "sha256" in signed.lower()
        assert "rsa-sha1" not in signed

    def test_sign_xml_uses_exclusive_c14n(
        self, cert_data, sample_rde
    ):
        from kilasifen.engine.firma import sign_xml

        xml = sample_rde.to_xml()
        signed = sign_xml(
            xml, cert_data, "test1234", sample_rde.DE.Id
        )

        assert "http://www.w3.org/2001/10/xml-exc-c14n#" in signed

    def test_sign_xml_uses_default_dsig_namespace(
        self, cert_data, sample_rde
    ):
        from kilasifen.engine.firma import sign_xml

        xml = sample_rde.to_xml()
        signed = sign_xml(
            xml, cert_data, "test1234", sample_rde.DE.Id
        )

        assert "<Signature xmlns=\"http://www.w3.org/2000/09/xmldsig#\">" in signed
        assert "<ds:Signature" not in signed

    def test_sign_xml_reference_uri(
        self, cert_data, sample_rde
    ):
        """Verifica que la Reference URI apunta al CDC."""
        from lxml import etree

        from kilasifen.engine.firma import sign_xml

        xml = sample_rde.to_xml()
        doc_id = sample_rde.DE.Id
        signed = sign_xml(xml, cert_data, "test1234", doc_id)

        root = etree.fromstring(signed.encode())
        ns = {"ds": "http://www.w3.org/2000/09/xmldsig#"}
        refs = root.findall(".//ds:Reference", ns)
        assert len(refs) >= 1

        uris = [r.get("URI", "") for r in refs]
        assert any(f"#{doc_id}" in uri for uri in uris)

    def test_sign_xml_roundtrip(self, cert_data, sample_rde):
        """Firma, vuelve a parsear y verifica la estructura."""
        from lxml import etree

        from kilasifen.engine.firma import sign_xml

        xml = sample_rde.to_xml()
        signed = sign_xml(
            xml, cert_data, "test1234", sample_rde.DE.Id
        )

        # Debe ser XML valido
        root = etree.fromstring(signed.encode())
        assert root is not None

        # Debe contener el elemento Signature
        ns = {"ds": "http://www.w3.org/2000/09/xmldsig#"}
        sig = root.find(".//ds:Signature", ns)
        assert sig is not None

        # Debe contener SignedInfo, SignatureValue y KeyInfo
        assert sig.find("ds:SignedInfo", ns) is not None
        assert sig.find("ds:SignatureValue", ns) is not None

    def test_sign_xml_invalid_cert(self, sample_rde):
        """Falla con un certificado invalido."""
        from kilasifen.engine.firma import sign_xml

        xml = sample_rde.to_xml()
        with pytest.raises(Exception):
            sign_xml(
                xml, b"invalid-pkcs12", "wrong", sample_rde.DE.Id
            )

    def test_sign_xml_bytes_input(
        self, cert_data, sample_rde
    ):
        """Acepta el XML como bytes."""
        from kilasifen.engine.firma import sign_xml

        xml = sample_rde.to_xml().encode()
        signed = sign_xml(
            xml, cert_data, "test1234", sample_rde.DE.Id
        )
        assert "SignatureValue" in signed

    def test_sign_xml_bytes_password(
        self, cert_data, sample_rde
    ):
        """Acepta la contrasena como bytes."""
        from kilasifen.engine.firma import sign_xml

        xml = sample_rde.to_xml()
        signed = sign_xml(
            xml, cert_data, b"test1234", sample_rde.DE.Id
        )
        assert "SignatureValue" in signed

    def test_sign_via_mixin(self, cert_data, sample_rde):
        """Firma a traves de BindingMixin.sign_xml()."""
        xml = sample_rde.to_xml()
        signed = sample_rde.sign_xml(
            xml, cert_data, "test1234", sample_rde.DE.Id
        )
        assert "SignatureValue" in signed

    def test_sign_xml_keeps_signature_before_gcamfufd(self, cert_data):
        """Mantiene Signature antes de gCamFuFD para cumplir DE_v150.xsd."""
        from lxml import etree

        from kilasifen.engine.firma import sign_xml

        ns = "http://ekuatia.set.gov.py/sifen/xsd"
        doc_id = "01800241355001001000000122026042411234567899"
        xml = (
            f'<rDE xmlns="{ns}"><dVerFor>150</dVerFor>'
            f'<DE Id="{doc_id}"><gTimb><iTiDE>1</iTiDE></gTimb></DE>'
            "<gCamFuFD><dCarQR>https://example.test/qr</dCarQR></gCamFuFD>"
            "</rDE>"
        )

        signed = sign_xml(xml, cert_data, "test1234", doc_id)
        root = etree.fromstring(signed.encode())
        child_names = [etree.QName(child).localname for child in root]
        assert child_names == ["dVerFor", "DE", "Signature", "gCamFuFD"]
