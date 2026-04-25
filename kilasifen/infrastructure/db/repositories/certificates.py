"""SQLAlchemy implementation of the certificate repository."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from kilasifen.domain.certificates.models import Certificate, ensure_single_active_certificate
from kilasifen.infrastructure.db.models import CertificateModel
from kilasifen.repositories.certificates import CertificateRepository


class SqlAlchemyCertificateRepository(CertificateRepository):
    """Persist certificates with SQLAlchemy."""

    def __init__(self, session: Session):
        self.session = session

    def save(self, certificate: Certificate) -> Certificate:
        existing = self.session.get(CertificateModel, certificate.id)
        if existing is None:
            model = CertificateModel(
                id=certificate.id,
                emitter_id=certificate.emitter_id,
                logical_name=certificate.logical_name,
                encrypted_p12=certificate.encrypted_p12,
                encrypted_password=certificate.encrypted_password,
                fingerprint=certificate.fingerprint,
                serial_number=certificate.serial_number,
                subject_summary=certificate.subject_summary,
                detected_ruc=certificate.detected_ruc,
                valid_from=certificate.valid_from,
                valid_until=certificate.valid_until,
                is_active=certificate.is_active,
                status=certificate.status,
                created_at=certificate.created_at,
                updated_at=certificate.updated_at,
            )
            self.session.add(model)
        else:
            existing.logical_name = certificate.logical_name
            existing.encrypted_p12 = certificate.encrypted_p12
            existing.encrypted_password = certificate.encrypted_password
            existing.fingerprint = certificate.fingerprint
            existing.serial_number = certificate.serial_number
            existing.subject_summary = certificate.subject_summary
            existing.detected_ruc = certificate.detected_ruc
            existing.valid_from = certificate.valid_from
            existing.valid_until = certificate.valid_until
            existing.is_active = certificate.is_active
            existing.status = certificate.status
            existing.updated_at = certificate.updated_at
        self.session.flush()
        return certificate

    def list_for_emitter(self, emitter_id: str) -> list[Certificate]:
        statement = select(CertificateModel).where(CertificateModel.emitter_id == emitter_id)
        models = self.session.scalars(statement).all()
        return [_to_domain(model) for model in models]

    def get_active_for_emitter(self, emitter_id: str) -> Certificate | None:
        certificates = self.list_for_emitter(emitter_id)
        return ensure_single_active_certificate(certificates, emitter_id)

    def get(self, certificate_id: str) -> Certificate | None:
        model = self.session.get(CertificateModel, certificate_id)
        if model is None:
            return None
        return _to_domain(model)


def _to_domain(model: CertificateModel) -> Certificate:
    return Certificate(
        id=model.id,
        emitter_id=model.emitter_id,
        logical_name=model.logical_name,
        encrypted_p12=model.encrypted_p12,
        encrypted_password=model.encrypted_password,
        fingerprint=model.fingerprint,
        serial_number=model.serial_number,
        subject_summary=model.subject_summary,
        detected_ruc=model.detected_ruc,
        valid_from=model.valid_from,
        valid_until=model.valid_until,
        is_active=model.is_active,
        status=model.status,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )
