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
_SLOW_HASH_ALGORITHM = "pbkdf2_sha256"
_FAST_HASH_ALGORITHM = "sha256"
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


def fingerprint_api_key(raw_key: str) -> str:
    """Hash a consumer credential with SHA-256.

    A consumer key is ``ks_`` plus 256 random bits (``secrets.token_urlsafe``),
    so nobody can guess it from its hash however fast the hash is: a slow KDF
    adds no protection there and cost ~50 ms of CPU on every request.
    Operator-chosen bootstrap keys, whose entropy is unknown, keep the salted
    PBKDF2 of :func:`hash_api_key`.
    """

    digest = hashlib.sha256(raw_key.encode("utf-8")).digest()
    return "$".join(
        (_FAST_HASH_ALGORITHM, base64.urlsafe_b64encode(digest).decode("ascii"))
    )


def is_slow_api_key_hash(encoded_hash: str) -> bool:
    """Tell whether ``encoded_hash`` is the salted PBKDF2 format."""

    return encoded_hash.startswith(f"{_SLOW_HASH_ALGORITHM}$")


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
            _SLOW_HASH_ALGORITHM,
            str(_PBKDF2_ITERATIONS),
            base64.urlsafe_b64encode(salt).decode("ascii"),
            base64.urlsafe_b64encode(digest).decode("ascii"),
        )
    )


def verify_api_key(raw_key: str, encoded_hash: str) -> bool:
    """Verify a stored credential hash (SHA-256 or PBKDF2) in constant time."""

    if encoded_hash.startswith(f"{_FAST_HASH_ALGORITHM}$"):
        try:
            expected = base64.urlsafe_b64decode(
                encoded_hash.split("$", 1)[1].encode("ascii")
            )
        except (ValueError, TypeError):
            return False
        actual = hashlib.sha256(raw_key.encode("utf-8")).digest()
        return hmac.compare_digest(actual, expected)
    try:
        algorithm, iterations_text, salt_text, expected_text = encoded_hash.split(
            "$", 3
        )
        if algorithm != _SLOW_HASH_ALGORITHM:
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
