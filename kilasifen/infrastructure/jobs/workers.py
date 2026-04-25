"""Worker entrypoints for background jobs."""

from kilasifen.application.jobs.service import JobService
from kilasifen.infrastructure.db.repositories.documents import SqlAlchemyDocumentRepository
from kilasifen.infrastructure.db.repositories.jobs import SqlAlchemyJobRepository
from kilasifen.infrastructure.db.session import build_engine, build_session_factory, session_scope


def process_document_job(*, job_id: str, database_url: str) -> dict[str, str]:
    """Hydrate a document-emission job context for later processing."""

    engine = build_engine(database_url)
    session_factory = build_session_factory(engine)

    with session_scope(session_factory) as session:
        job_service = JobService(SqlAlchemyJobRepository(session))
        document_repository = SqlAlchemyDocumentRepository(session)
        job, document = job_service.get_document_job_context(
            job_id=job_id,
            document_repository=document_repository,
        )

    return {
        "job_id": job.id,
        "job_type": job.job_type,
        "document_id": document.id,
        "document_type": document.document_type,
    }
