"""Security primitives and authenticated caller identity."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass

from kilasifen.api.errors import ApiError

PLATFORM_ADMIN_SCOPE = "platform:admin"
TENANT_READ_SCOPE = "tenant:read"
TENANT_WRITE_SCOPE = "tenant:write"
FISCAL_WRITE_SCOPE = "fiscal:write"
SECRETS_WRITE_SCOPE = "secrets:write"
#: Creates emitters owned by the credential's own consumer (self-service
#: onboarding of an ERP's customers); never someone else's.
EMITTERS_CREATE_SCOPE = "emitters:create"

_PBKDF2_ALGORITHM = "sha256"
_PBKDF2_ITERATIONS = 210_000
_SALT_BYTES = 16
_KEY_PREFIX_LENGTH = 12


@dataclass(frozen=True, slots=True)
class ApiKeyPrincipal:
    """Non-secret identity and authorization claims for one API key."""

    key_id: str
    consumer_id: str
    scopes: frozenset[str]
    emitter_ids: frozenset[str]

    @property
    def is_platform_admin(self) -> bool:
        return PLATFORM_ADMIN_SCOPE in self.scopes

    def require_scope(self, scope: str) -> None:
        if self.is_platform_admin or scope in self.scopes:
            return
        raise ApiError(
            status_code=403,
            code="auth.insufficient_scope",
            message="The credential lacks the required scope.",
            category="authorization",
        )

    def require_emitter(self, emitter_id: str) -> None:
        if self.is_platform_admin or emitter_id in self.emitter_ids:
            return
        raise ApiError(
            status_code=404,
            code="emitters.not_found",
            message="Resource was not found.",
            category="not_found",
        )


def key_prefix(raw_key: str) -> str:
    """Return the non-secret lookup prefix stored beside a credential hash."""

    return raw_key[:_KEY_PREFIX_LENGTH]


def hash_api_key(raw_key: str, *, salt: bytes | None = None) -> str:
    """Hash a credential with a salted, deliberately expensive KDF."""

    salt = salt or secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        _PBKDF2_ALGORITHM,
        raw_key.encode("utf-8"),
        salt,
        _PBKDF2_ITERATIONS,
    )
    return "$".join(
        (
            "pbkdf2_sha256",
            str(_PBKDF2_ITERATIONS),
            base64.urlsafe_b64encode(salt).decode("ascii"),
            base64.urlsafe_b64encode(digest).decode("ascii"),
        )
    )


def verify_api_key(raw_key: str, encoded_hash: str) -> bool:
    """Verify a stored credential hash using constant-time comparison."""

    try:
        algorithm, iterations_text, salt_text, expected_text = encoded_hash.split(
            "$", 3
        )
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_text)
        salt = base64.urlsafe_b64decode(salt_text.encode("ascii"))
        expected = base64.urlsafe_b64decode(expected_text.encode("ascii"))
    except (ValueError, TypeError):
        return False
    actual = hashlib.pbkdf2_hmac(
        _PBKDF2_ALGORITHM,
        raw_key.encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(actual, expected)
