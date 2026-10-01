"""Emitter application service layer."""

from datetime import datetime, timezone
from uuid import uuid4

from kilasifen.application.emitters.guards import require_active_emitter
from kilasifen.domain.common.errors import (
    ConflictError,
    NotFoundError,
    UnprocessableEntityError,
)
from kilasifen.domain.emitters.models import Emitter, EmitterSummary
from kilasifen.repositories.emitters import EmitterRepository


class EmitterService:
    """Use cases for emitter management."""

    def __init__(
        self,
        repository: EmitterRepository,
        deployment_tax_environment: str = "test",
    ):
        self.repository = repository
        self.deployment_tax_environment = deployment_tax_environment

    def create_emitter(
        self,
        *,
        external_id: str | None,
        ruc: str,
        dv: str,
        legal_name: str,
        tax_environment: str,
        csc: str | None,
        csc_id: str | None,
        owner_consumer_id: str | None = None,
    ) -> Emitter:
        self._validate_tax_environment(tax_environment)
        if external_id and self.repository.get_by_external_id(external_id) is not None:
            raise ConflictError("emitters.external_id_conflict")
        if self.repository.get_by_tax_id(ruc, dv) is not None:
            raise ConflictError("emitters.tax_id_conflict")

        timestamp = _now()
        emitter = Emitter(
            id=str(uuid4()),
            external_id=external_id,
            ruc=ruc,
            dv=dv,
            legal_name=legal_name,
            tax_environment=tax_environment,
            status="active",
            csc=csc,
            csc_id=csc_id,
            created_at=timestamp,
            updated_at=timestamp,
        )
        saved = self.repository.save(emitter)
        if owner_consumer_id is not None:
            self.repository.grant_owner(
                consumer_id=owner_consumer_id,
                emitter_id=saved.id,
            )
        return saved

    def get_emitter(self, emitter_id: str) -> Emitter:
        emitter = self.repository.get(emitter_id)
        if emitter is None:
            raise NotFoundError("emitters.not_found")
        return emitter

    def update_emitter(
        self,
        emitter_id: str,
        *,
        legal_name: str | None,
        tax_environment: str | None,
        csc: str | None,
        csc_id: str | None,
    ) -> EmitterSummary:
        if tax_environment is not None:
            self._validate_tax_environment(tax_environment)
        updates_secret = csc is not None or csc_id is not None
        if updates_secret:
            require_active_emitter(self.repository, emitter_id)
        timestamp = _now()
        result: EmitterSummary | None = None
        if legal_name is not None or tax_environment is not None or not updates_secret:
            result = self.repository.update_metadata(
                emitter_id,
                legal_name=legal_name,
                tax_environment=tax_environment,
                updated_at=timestamp,
            )
        if updates_secret:
            result = self.repository.update_secret(
                emitter_id,
                csc=csc,
                csc_id=csc_id,
                updated_at=timestamp,
            )
        if result is None:
            raise NotFoundError("emitters.not_found")
        return result

    def _validate_tax_environment(self, tax_environment: str) -> None:
        if tax_environment != self.deployment_tax_environment:
            raise UnprocessableEntityError(
                "emitters.tax_environment_mismatch",
                details={"allowed": self.deployment_tax_environment},
            )

    def deactivate_emitter(self, emitter_id: str) -> EmitterSummary:
        emitter = self.repository.deactivate(emitter_id, updated_at=_now())
        if emitter is None:
            raise NotFoundError("emitters.not_found")
        return emitter


def _now() -> datetime:
    return datetime.now(timezone.utc)
