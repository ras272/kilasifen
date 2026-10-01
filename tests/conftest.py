"""Shared test fixtures that never depend on committed fiscal secrets."""

from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

_TEST_CERTIFICATE_PATH = Path(__file__).with_name("test_cert.pfx")
_TEST_CERTIFICATE_PASSWORD = b"test1234"


@pytest.fixture(scope="session", autouse=True)
def ephemeral_test_certificate() -> Iterator[None]:
    """Generate the repository's fictional PKCS#12 fixture for this test run."""

    private_key = rsa.generate_private_key(public_exponent=65_537, key_size=2_048)
    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "PY"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "KilaSifen Test Only"),
            x509.NameAttribute(NameOID.COMMON_NAME, "Ephemeral Test Certificate"),
            x509.NameAttribute(NameOID.SERIAL_NUMBER, "80024135"),
        ]
    )
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime(2025, 1, 1, tzinfo=timezone.utc))
        .not_valid_after(datetime(2035, 1, 1, tzinfo=timezone.utc))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(private_key, hashes.SHA256())
    )
    pfx = pkcs12.serialize_key_and_certificates(
        name=b"kilasifen-ephemeral-test",
        key=private_key,
        cert=certificate,
        cas=None,
        encryption_algorithm=serialization.BestAvailableEncryption(
            _TEST_CERTIFICATE_PASSWORD
        ),
    )
    _TEST_CERTIFICATE_PATH.write_bytes(pfx)
    try:
        yield
    finally:
        _TEST_CERTIFICATE_PATH.unlink(missing_ok=True)
