"""Emitter application service layer."""

from datetime import datetime, timezone
from uuid import uuid4

from kilasifen.application.emitters.fiscal_profile import normalize_fiscal_profile
from kilasifen.application.emitters.guards import require_active_emitter
from kilasifen.application.emitters.identity import (
    normalize_csc_id,
    validate_csc,
    validate_legal_name,
    validate_tax_id,
)
from kilasifen.domain.common.errors import (
    ConflictError,
    NotFoundError,
    UnprocessableEntityError,
)
from kilasifen.domain.emitters.fiscal_profile import EmitterFiscalProfile
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
        fiscal_profile: EmitterFiscalProfile | None = None,
    ) -> Emitter:
        self._validate_tax_environment(tax_environment)
        validate_tax_id(ruc, dv)
        validate_legal_name(legal_name)
        csc, csc_id = _validated_csc(csc, csc_id)
        if fiscal_profile is not None:
            fiscal_profile = normalize_fiscal_profile(fiscal_profile)
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
            fiscal_profile=fiscal_profile,
        )
        saved = self.repository.save(emitter)
        if owner_consumer_id is not None:
            self.repository.grant_owner(
                consumer_id=owner_consumer_id,
                emitter_id=saved.id,
            )
        return saved

    def list_emitters(
        self,
        *,
        owner_consumer_id: str | None,
        external_id: str | None = None,
        ruc: str | None = None,
        limit: int = 50,
    ) -> list[Emitter]:
        """Emitters of ``owner_consumer_id`` (all when None), newest first.

        ``external_id`` must match exactly; ``ruc`` may come as ``RUC-DV``,
        and only the RUC is compared.
        """

        normalized_ruc = ruc.strip().split("-", 1)[0] if ruc else None
        return self.repository.list_filtered(
            owner_consumer_id=owner_consumer_id,
            external_id=external_id,
            ruc=normalized_ruc or None,
            limit=limit,
        )

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
        fiscal_profile: EmitterFiscalProfile | None = None,
    ) -> EmitterSummary:
        """Update metadata, secrets or the fiscal profile (replaced whole)."""

        if tax_environment is not None:
            self._validate_tax_environment(tax_environment)
        if legal_name is not None:
            validate_legal_name(legal_name)
        csc, csc_id = _validated_csc(csc, csc_id)
        if fiscal_profile is not None:
            fiscal_profile = normalize_fiscal_profile(fiscal_profile)
        updates_secret = csc is not None or csc_id is not None
        updates_metadata = (
            legal_name is not None
            or tax_environment is not None
            or fiscal_profile is not None
        )
        if updates_secret:
            require_active_emitter(self.repository, emitter_id)
        timestamp = _now()
        result: EmitterSummary | None = None
        if updates_metadata or not updates_secret:
            result = self.repository.update_metadata(
                emitter_id,
                legal_name=legal_name,
                tax_environment=tax_environment,
                fiscal_profile=fiscal_profile,
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


def _validated_csc(
    csc: str | None, csc_id: str | None
) -> tuple[str | None, str | None]:
    if csc is not None:
        validate_csc(csc)
    if csc_id is not None:
        csc_id = normalize_csc_id(csc_id)
    return csc, csc_id


def _now() -> datetime:
    return datetime.now(timezone.utc)
