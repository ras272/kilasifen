"""SQLAlchemy implementation of the emitter repository."""

from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from kilasifen.domain.common.errors import NotFoundError
from kilasifen.domain.emitters.models import Emitter, EmitterSummary
from kilasifen.infrastructure.crypto.certificate_store import EncryptedCertificateStore
from kilasifen.infrastructure.db.locks import run_with_lock_timeout
from kilasifen.infrastructure.db.models import (
    ConsumerEmitterModel,
    ConsumerModel,
    EmitterModel,
)
from kilasifen.repositories.emitters import EmitterRepository

#: Longest wait for the emitter row lock before answering a retryable 503.
#: The lock is only held by short transactions (never across a SIFEN call).
EMITTER_LOCK_TIMEOUT_MS = 5000


class SqlAlchemyEmitterRepository(EmitterRepository):
    """Persist emitters with SQLAlchemy."""

    def __init__(
        self,
        session: Session,
        secret_store: EncryptedCertificateStore | None = None,
    ):
        self.session = session
        self.secret_store = secret_store

    def save(self, emitter: Emitter) -> Emitter:
        existing = self.session.get(EmitterModel, emitter.id)
        if existing is None:
            model = EmitterModel(
                id=emitter.id,
                external_id=emitter.external_id,
                ruc=emitter.ruc,
                dv=emitter.dv,
                legal_name=emitter.legal_name,
                tax_environment=emitter.tax_environment,
                status=emitter.status,
                csc=self._encrypt_csc(emitter.csc),
                csc_id=emitter.csc_id,
                created_at=emitter.created_at,
                updated_at=emitter.updated_at,
            )
            self.session.add(model)
        else:
            existing.external_id = emitter.external_id
            existing.ruc = emitter.ruc
            existing.dv = emitter.dv
            existing.legal_name = emitter.legal_name
            existing.tax_environment = emitter.tax_environment
            existing.status = emitter.status
            existing.csc = self._encrypt_csc(emitter.csc)
            existing.csc_id = emitter.csc_id
            existing.updated_at = emitter.updated_at
        self.session.flush()
        return emitter

    def get(self, emitter_id: str) -> Emitter | None:
        model = self.session.get(EmitterModel, emitter_id)
        if model is None:
            return None
        return _to_domain(model, self.secret_store)

    def get_status(self, emitter_id: str) -> str | None:
        statement = select(EmitterModel.status).where(EmitterModel.id == emitter_id)
        return self.session.scalar(statement)

    def get_status_for_update(self, emitter_id: str) -> str | None:
        statement = (
            select(EmitterModel.status)
            .where(EmitterModel.id == emitter_id)
            .with_for_update()
        )
        return run_with_lock_timeout(
            self.session,
            lambda: self.session.scalar(statement),
            timeout_ms=EMITTER_LOCK_TIMEOUT_MS,
            error_code="emitters.lock_timeout",
        )

    def lock_row(self, emitter_id: str) -> None:
        self.session.execute(
            select(EmitterModel.id)
            .where(EmitterModel.id == emitter_id)
            .with_for_update()
        )

    def update_metadata(
        self,
        emitter_id: str,
        *,
        legal_name: str | None,
        tax_environment: str | None,
        updated_at: datetime,
    ) -> EmitterSummary | None:
        values: dict[str, Any] = {"updated_at": updated_at}
        if legal_name is not None:
            values["legal_name"] = legal_name
        if tax_environment is not None:
            values["tax_environment"] = tax_environment
        statement = (
            update(EmitterModel)
            .where(EmitterModel.id == emitter_id)
            .values(**values)
            .returning(*_SUMMARY_COLUMNS)
        )
        return _summary_from_mapping(
            self.session.execute(statement).mappings().one_or_none()
        )

    def update_secret(
        self,
        emitter_id: str,
        *,
        csc: str | None,
        csc_id: str | None,
        updated_at: datetime,
    ) -> EmitterSummary | None:
        values: dict[str, Any] = {"updated_at": updated_at}
        if csc is not None:
            values["csc"] = self._encrypt_csc(csc)
        if csc_id is not None:
            values["csc_id"] = csc_id
        statement = (
            update(EmitterModel)
            .where(EmitterModel.id == emitter_id)
            .values(**values)
            .returning(*_SUMMARY_COLUMNS)
        )
        return _summary_from_mapping(
            self.session.execute(statement).mappings().one_or_none()
        )

    def deactivate(
        self,
        emitter_id: str,
        *,
        updated_at: datetime,
    ) -> EmitterSummary | None:
        statement = (
            update(EmitterModel)
            .where(EmitterModel.id == emitter_id)
            .values(status="inactive", updated_at=updated_at)
            .returning(*_SUMMARY_COLUMNS)
        )
        return _summary_from_mapping(
            self.session.execute(statement).mappings().one_or_none()
        )

    def get_by_external_id(self, external_id: str) -> Emitter | None:
        statement = select(EmitterModel).where(EmitterModel.external_id == external_id)
        model = self.session.scalar(statement)
        if model is None:
            return None
        return _to_domain(model, self.secret_store)

    def get_by_tax_id(self, ruc: str, dv: str) -> Emitter | None:
        statement = select(EmitterModel).where(
            EmitterModel.ruc == ruc,
            EmitterModel.dv == dv,
        )
        model = self.session.scalar(statement)
        if model is None:
            return None
        return _to_domain(model, self.secret_store)

    def list_all(self) -> list[Emitter]:
        statement = select(EmitterModel).order_by(EmitterModel.created_at.desc())
        return [
            _to_domain(model, self.secret_store)
            for model in self.session.scalars(statement)
        ]

    def grant_owner(self, *, consumer_id: str, emitter_id: str) -> None:
        if self.session.get(ConsumerModel, consumer_id) is None:
            raise NotFoundError("consumers.not_found")
        existing = self.session.scalar(
            select(ConsumerEmitterModel).where(
                ConsumerEmitterModel.emitter_id == emitter_id
            )
        )
        if existing is None:
            self.session.add(
                ConsumerEmitterModel(consumer_id=consumer_id, emitter_id=emitter_id)
            )
            self.session.flush()
            return
        if existing.consumer_id != consumer_id:
            raise ValueError("Emitter already belongs to another consumer")

    def _encrypt_csc(self, csc: str | None) -> str | None:
        if csc is None:
            return None
        if self.secret_store is None:
            raise RuntimeError("Encryption key is required to persist CSC material")
        return self.secret_store.encrypt_text(csc)


def _to_domain(
    model: EmitterModel,
    secret_store: EncryptedCertificateStore | None,
) -> Emitter:
    csc: str | None = None
    if model.csc is not None:
        if secret_store is None:
            raise RuntimeError("Encryption key is required to read CSC material")
        csc = secret_store.decrypt_text(model.csc)
    return Emitter(
        id=model.id,
        external_id=model.external_id,
        ruc=model.ruc,
        dv=model.dv,
        legal_name=model.legal_name,
        tax_environment=model.tax_environment,
        status=model.status,
        csc=csc,
        csc_id=model.csc_id,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


_SUMMARY_COLUMNS = (
    EmitterModel.id,
    EmitterModel.external_id,
    EmitterModel.ruc,
    EmitterModel.dv,
    EmitterModel.legal_name,
    EmitterModel.tax_environment,
    EmitterModel.status,
    EmitterModel.csc.is_not(None).label("csc_configured"),
    EmitterModel.csc_id,
    EmitterModel.created_at,
    EmitterModel.updated_at,
)


def _summary_from_mapping(row) -> EmitterSummary | None:
    if row is None:
        return None
    return EmitterSummary(
        id=row["id"],
        external_id=row["external_id"],
        ruc=row["ruc"],
        dv=row["dv"],
        legal_name=row["legal_name"],
        tax_environment=row["tax_environment"],
        status=row["status"],
        csc_configured=row["csc_configured"],
        csc_id=row["csc_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
