"""Encrypted storage helpers for certificate material."""

from cryptography.fernet import Fernet


class EncryptedCertificateStore:
    """Encrypt and decrypt certificate blobs and passwords."""

    def __init__(self, encryption_key: str):
        self._fernet = Fernet(encryption_key.encode())

    def encrypt_bytes(self, raw_value: bytes) -> str:
        return self._fernet.encrypt(raw_value).decode()

    def decrypt_bytes(self, encrypted_value: str) -> bytes:
        return self._fernet.decrypt(encrypted_value.encode())

    def encrypt_text(self, raw_value: str) -> str:
        return self.encrypt_bytes(raw_value.encode())

    def decrypt_text(self, encrypted_value: str) -> str:
        return self.decrypt_bytes(encrypted_value).decode()
