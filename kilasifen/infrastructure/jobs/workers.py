"""Worker entrypoints for background jobs."""

from dataclasses import replace
from datetime import date

from pysifen.sdk.errors import (
    SifenRejectionError,
    SifenTimeoutError,
    SifenTransportError,
    SifenValidationError,
)

from kilasifen.infrastructure.crypto.certificate_store import EncryptedCertificateStore
from kilasifen.infrastructure.db.repositories.certificates import SqlAlchemyCertificateRepository
from kilasifen.application.jobs.service import JobService
from kilasifen.infrastructure.db.repositories.documents import SqlAlchemyDocumentRepository
from kilasifen.infrastructure.db.repositories.emitters import SqlAlchemyEmitterRepository
from kilasifen.infrastructure.db.repositories.jobs import SqlAlchemyJobRepository
from kilasifen.infrastructure.db.repositories.stampings import SqlAlchemyStampingRepository
from kilasifen.infrastructure.db.session import build_engine, build_session_factory, session_scope
from kilasifen.infrastructure.sifen.engine import DocumentEmissionEngine, PysifenEmissionEngine


def process_document_job(
    *,
    job_id: str,
    database_url: str,
    encryption_key: str,
    emission_engine: DocumentEmissionEngine | None = None,
    current_date: date | None = None,
) -> dict[str, str]:
    """Process a document-emission job using the configured engine."""

    engine = build_engine(database_url)
    session_factory = build_session_factory(engine)
    emission_engine = emission_engine or PysifenEmissionEngine()
    certificate_store = EncryptedCertificateStore(encryption_key)

    with session_scope(session_factory) as session:
        job_repository = SqlAlchemyJobRepository(session)
        job_service = JobService(job_repository)
        document_repository = SqlAlchemyDocumentRepository(session)
        emitter_repository = SqlAlchemyEmitterRepository(session)
        certificate_repository = SqlAlchemyCertificateRepository(session)
        stamping_repository = SqlAlchemyStampingRepository(session)
        job, document = job_service.get_document_job_context(
            job_id=job_id,
            document_repository=document_repository,
        )
        emitter = emitter_repository.get(document.emitter_id)
        if emitter is None:
            raise RuntimeError("Emitter not found for document job")
        certificate = certificate_repository.get_active_for_emitter(document.emitter_id)
        if certificate is None:
            raise RuntimeError("Active certificate not configured")
        stamping = stamping_repository.get_active_for_emitter(
            document.emitter_id,
            on_date=current_date or date.today(),
        )
        if stamping is None:
            raise RuntimeError("Active stamping not configured")

        certificate_bytes = certificate_store.decrypt_bytes(certificate.encrypted_p12)
        certificate_password = certificate_store.decrypt_text(certificate.encrypted_password)

        try:
            outcome = emission_engine.emit_document(
                document=document,
                emitter=emitter,
                certificate=certificate,
                certificate_bytes=certificate_bytes,
                certificate_password=certificate_password,
                stamping=stamping,
            )
            updated_document = replace(
                document,
                generated_xml=outcome.generated_xml,
                signed_xml=outcome.signed_xml,
                sifen_request_xml=outcome.request_xml,
                sifen_response_raw=outcome.response_raw,
                internal_status=outcome.sifen_status,
                sifen_status=outcome.sifen_status,
                sifen_result_code=outcome.result_code,
                sifen_result_message=outcome.result_message,
            )
            updated_job = replace(
                job,
                status="succeeded",
                error_snapshot=None,
            )
        except SifenValidationError as exc:
            updated_document = replace(document, internal_status="failed")
            updated_job = replace(
                job,
                status="failed",
                error_snapshot={"category": "fiscal_validation", "message": str(exc)},
            )
        except (SifenTimeoutError, SifenTransportError) as exc:
            updated_document = replace(document, internal_status="retry_pending")
            updated_job = replace(
                job,
                status="retry_scheduled",
                error_snapshot={"category": "transport", "message": str(exc)},
            )
        except SifenRejectionError as exc:
            updated_document = replace(
                document,
                internal_status="rejected",
                sifen_status="rejected",
                sifen_result_code=exc.code,
                sifen_result_message=exc.message,
            )
            updated_job = replace(
                job,
                status="failed",
                error_snapshot={
                    "category": "sifen_rejection",
                    "code": exc.code,
                    "message": exc.message,
                },
            )

        document_repository.save(updated_document)
        job_repository.save(updated_job)

        return {
            "job_id": updated_job.id,
            "job_type": updated_job.job_type,
            "document_id": updated_document.id,
            "document_type": updated_document.document_type,
            "job_status": updated_job.status,
            "document_status": updated_document.internal_status,
        }
