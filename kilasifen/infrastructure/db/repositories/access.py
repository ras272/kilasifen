"""SQL access administration repository."""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from kilasifen.domain.access.models import ApiCredential, Consumer
from kilasifen.infrastructure.db.models import ApiKeyModel, ConsumerModel
from kilasifen.repositories.access import AccessRepository
from kilasifen.security import hash_api_key, key_prefix


class SqlAlchemyAccessRepository(AccessRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_consumer(self, *, name: str) -> Consumer:
        model = ConsumerModel(name=name, status="active")
        self.session.add(model)
        self.session.flush()
        return _consumer(model)

    def get_consumer(self, consumer_id: str) -> Consumer | None:
        model = self.session.get(ConsumerModel, consumer_id)
        return _consumer(model) if model is not None else None

    def get_consumer_by_name(self, name: str) -> Consumer | None:
        model = self.session.scalar(
            select(ConsumerModel).where(ConsumerModel.name == name)
        )
        return _consumer(model) if model is not None else None

    def issue_credential(
        self,
        *,
        consumer_id: str,
        name: str,
        raw_key: str,
        scopes: tuple[str, ...],
    ) -> ApiCredential:
        model = ApiKeyModel(
            consumer_id=consumer_id,
            name=name,
            key_prefix=key_prefix(raw_key),
            key_hash=hash_api_key(raw_key),
            scopes=list(scopes),
            status="active",
        )
        self.session.add(model)
        self.session.flush()
        return _credential(model)

    def revoke_credential(
        self,
        *,
        consumer_id: str,
        credential_id: str,
    ) -> ApiCredential | None:
        model = self.session.scalar(
            select(ApiKeyModel).where(
                ApiKeyModel.id == credential_id,
                ApiKeyModel.consumer_id == consumer_id,
            )
        )
        if model is None:
            return None
        model.status = "revoked"
        model.updated_at = datetime.now(timezone.utc)
        self.session.flush()
        return _credential(model)


def _consumer(model: ConsumerModel) -> Consumer:
    return Consumer(
        id=model.id,
        name=model.name,
        status=model.status,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _credential(model: ApiKeyModel) -> ApiCredential:
    return ApiCredential(
        id=model.id,
        consumer_id=model.consumer_id,
        name=model.name,
        key_prefix=model.key_prefix,
        scopes=tuple(model.scopes),
        status=model.status,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )
