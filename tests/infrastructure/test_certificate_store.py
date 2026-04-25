from cryptography.fernet import Fernet

from kilasifen.infrastructure.crypto.certificate_store import EncryptedCertificateStore


def test_certificate_store_roundtrips_bytes_and_text() -> None:
    store = EncryptedCertificateStore(Fernet.generate_key().decode())

    encrypted_bytes = store.encrypt_bytes(b"hello")
    encrypted_text = store.encrypt_text("secret-password")

    assert encrypted_bytes != "hello"
    assert encrypted_text != "secret-password"
    assert store.decrypt_bytes(encrypted_bytes) == b"hello"
    assert store.decrypt_text(encrypted_text) == "secret-password"
