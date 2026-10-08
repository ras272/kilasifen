"""Database-backed API credential authentication."""

from __future__ import annotations

import hashlib
from collections.abc import MutableMapping
from datetime import datetime, timezone
from uuid import UUID, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from kilasifen.infrastructure.db.models import (
    ApiKeyModel,
    ConsumerEmitterModel,
    ConsumerModel,
)
from kilasifen.security import (
    PLATFORM_ADMIN_SCOPE,
    ApiKeyPrincipal,
    fingerprint_api_key,
    hash_api_key,
    is_slow_api_key_hash,
    key_prefix,
    verify_api_key,
)

_BOOTSTRAP_NAMESPACE = UUID("1d66f979-a2d4-47e8-b337-e0e9ff18c31f")
_BOOTSTRAP_CONSUMER_ID = str(uuid5(_BOOTSTRAP_NAMESPACE, "platform-bootstrap"))


class SqlAlchemyApiKeyRepository:
    """Resolve API credentials without retaining their raw values."""

    def __init__(self, session: Session):
        self.session = session

    def authenticate(self, raw_key: str) -> ApiKeyPrincipal | None:
        """Authenticate one tenant credential.

        A credential still stored with the old PBKDF2 hash is moved to SHA-256
        the first time it is used: its raw value is only in hand right then.
        """

        statement = select(ApiKeyModel).where(
            ApiKeyModel.key_prefix == key_prefix(raw_key),
            ApiKeyModel.status == "active",
            ApiKeyModel.consumer_id != _BOOTSTRAP_CONSUMER_ID,
        )
        for credential in self.session.scalars(statement):
            if verify_api_key(raw_key, credential.key_hash):
                if is_slow_api_key_hash(credential.key_hash):
                    credential.key_hash = fingerprint_api_key(raw_key)
                    credential.updated_at = datetime.now(timezone.utc)
                    self.session.flush()
                return self._principal(credential)
        return None

    def authenticate_bootstrap(
        self,
        raw_key: str,
        *,
        position: int,
        ensured: MutableMapping[int, str],
    ) -> ApiKeyPrincipal | None:
        """Principal of a bootstrap key already matched against the settings.

        The configured key is the source of truth. Its stored PBKDF2 hash is
        checked, and replaced when the key changed, once per process and key
        (``ensured`` maps each position to the SHA-256 of the key last
        ensured there), not on every request.
        """

        fingerprint = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
        credential = None
        if ensured.get(position) == fingerprint:
            credential = self._bootstrap_credential(position)
        if credential is None:
            # First use in this process, a changed key, or a database that
            # changed under the process: check and store it again.
            self.ensure_bootstrap_admin(raw_key, position=position)
            credential = self._bootstrap_credential(position)
        if credential is None:
            return None
        ensured[position] = fingerprint
        return self._principal(credential)

    def _bootstrap_credential(self, position: int) -> ApiKeyModel | None:
        return self.session.scalar(
            select(ApiKeyModel).where(
                ApiKeyModel.consumer_id == _BOOTSTRAP_CONSUMER_ID,
                ApiKeyModel.name == f"bootstrap-{position}",
                ApiKeyModel.status == "active",
            )
        )

    def ensure_bootstrap_admin(self, raw_key: str, *, position: int) -> None:
        """Persist a configured bootstrap key as a one-way hash."""

        consumer = self.session.get(ConsumerModel, _BOOTSTRAP_CONSUMER_ID)
        if consumer is None:
            self.session.add(
                ConsumerModel(
                    id=_BOOTSTRAP_CONSUMER_ID,
                    name="Platform bootstrap administrator",
                    status="active",
                )
            )
            self.session.flush()

        statement = select(ApiKeyModel).where(
            ApiKeyModel.consumer_id == _BOOTSTRAP_CONSUMER_ID,
            ApiKeyModel.name == f"bootstrap-{position}",
        )
        credential = self.session.scalar(statement)
        if credential is not None and verify_api_key(raw_key, credential.key_hash):
            return
        if credential is None:
            credential = ApiKeyModel(
                consumer_id=_BOOTSTRAP_CONSUMER_ID,
                name=f"bootstrap-{position}",
                key_prefix=key_prefix(raw_key),
                key_hash=hash_api_key(raw_key),
                scopes=[PLATFORM_ADMIN_SCOPE],
                status="active",
            )
            self.session.add(credential)
        else:
            credential.key_prefix = key_prefix(raw_key)
            credential.key_hash = hash_api_key(raw_key)
            credential.scopes = [PLATFORM_ADMIN_SCOPE]
            credential.status = "active"
            credential.updated_at = datetime.now(timezone.utc)
        self.session.flush()

    def grant_emitter(self, *, consumer_id: str, emitter_id: str) -> None:
        existing = self.session.scalar(
            select(ConsumerEmitterModel).where(
                ConsumerEmitterModel.emitter_id == emitter_id
            )
        )
        if existing is None:
            self.session.add(
                ConsumerEmitterModel(
                    consumer_id=consumer_id,
                    emitter_id=emitter_id,
                )
            )
            self.session.flush()
        elif existing.consumer_id != consumer_id:
            raise ValueError("Emitter already belongs to another consumer")

    def _principal(self, credential: ApiKeyModel) -> ApiKeyPrincipal:
        emitter_ids = self.session.scalars(
            select(ConsumerEmitterModel.emitter_id).where(
                ConsumerEmitterModel.consumer_id == credential.consumer_id
            )
        ).all()
        return ApiKeyPrincipal(
            key_id=credential.id,
            consumer_id=credential.consumer_id,
            scopes=frozenset(credential.scopes),
            emitter_ids=frozenset(emitter_ids),
        )
