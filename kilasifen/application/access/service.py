"""Consumer and credential lifecycle service."""

import secrets

from kilasifen.domain.access.models import ApiCredential, Consumer
from kilasifen.domain.common.errors import (
    ConflictError,
    NotFoundError,
    UnprocessableEntityError,
)
from kilasifen.repositories.access import AccessRepository
from kilasifen.security import (
    FISCAL_WRITE_SCOPE,
    SECRETS_WRITE_SCOPE,
    TENANT_READ_SCOPE,
    TENANT_WRITE_SCOPE,
)

ALLOWED_CONSUMER_SCOPES = frozenset(
    {TENANT_READ_SCOPE, TENANT_WRITE_SCOPE, FISCAL_WRITE_SCOPE, SECRETS_WRITE_SCOPE}
)


class AccessService:
    def __init__(self, repository: AccessRepository) -> None:
        self.repository = repository

    def create_consumer(self, *, name: str) -> Consumer:
        normalized_name = name.strip()
        if self.repository.get_consumer_by_name(normalized_name) is not None:
            raise ConflictError("consumers.name_conflict")
        return self.repository.create_consumer(name=normalized_name)

    def issue_credential(
        self,
        *,
        consumer_id: str,
        name: str,
        scopes: list[str],
    ) -> tuple[ApiCredential, str]:
        if self.repository.get_consumer(consumer_id) is None:
            raise NotFoundError("consumers.not_found")
        normalized_scopes = tuple(sorted(set(scopes)))
        if (
            not normalized_scopes
            or not set(normalized_scopes) <= ALLOWED_CONSUMER_SCOPES
        ):
            raise UnprocessableEntityError(
                "credentials.invalid_scopes",
                details={"allowed": sorted(ALLOWED_CONSUMER_SCOPES)},
            )
        raw_key = f"ks_{secrets.token_urlsafe(32)}"
        credential = self.repository.issue_credential(
            consumer_id=consumer_id,
            name=name.strip(),
            raw_key=raw_key,
            scopes=normalized_scopes,
        )
        return credential, raw_key

    def revoke_credential(
        self, *, consumer_id: str, credential_id: str
    ) -> ApiCredential:
        credential = self.repository.revoke_credential(
            consumer_id=consumer_id,
            credential_id=credential_id,
        )
        if credential is None:
            raise NotFoundError("credentials.not_found")
        return credential
