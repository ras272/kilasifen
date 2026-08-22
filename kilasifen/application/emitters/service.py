"""Emitter application service layer."""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from kilasifen.application.emitters.guards import require_active_emitter
from kilasifen.domain.common.errors import (
    ConflictError,
    NotFoundError,
    UnprocessableEntityError,
)
from kilasifen.domain.emitters.models import Emitter
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
    ) -> Emitter:
        if tax_environment is not None:
            self._validate_tax_environment(tax_environment)
        if csc is not None or csc_id is not None:
            require_active_emitter(self.repository, emitter_id)
        emitter = self.get_emitter(emitter_id)
        updated = replace(
            emitter,
            legal_name=legal_name if legal_name is not None else emitter.legal_name,
            tax_environment=(
                tax_environment
                if tax_environment is not None
                else emitter.tax_environment
            ),
            csc=csc if csc is not None else emitter.csc,
            csc_id=csc_id if csc_id is not None else emitter.csc_id,
            updated_at=_now(),
        )
        return self.repository.save(updated)

    def _validate_tax_environment(self, tax_environment: str) -> None:
        if tax_environment != self.deployment_tax_environment:
            raise UnprocessableEntityError(
                "emitters.tax_environment_mismatch",
                details={"allowed": self.deployment_tax_environment},
            )

    def deactivate_emitter(self, emitter_id: str) -> Emitter:
        emitter = self.get_emitter(emitter_id)
        updated = replace(emitter, status="inactive", updated_at=_now())
        return self.repository.save(updated)


def _now() -> datetime:
    return datetime.now(UTC)
