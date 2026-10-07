"""Job API routes."""

from fastapi import APIRouter, Depends, Query, Request

from kilasifen.api.deps import (
    get_admin_principal,
    get_admin_service,
    get_job_service,
    require_emitter_read,
    require_fiscal_write,
)
from kilasifen.api.schemas.common import Pagination
from kilasifen.api.schemas.jobs import (
    JobData,
    JobEnvelope,
    JobListData,
    JobListEnvelope,
    JobResponse,
)
from kilasifen.application.admin.service import AdminConsoleService
from kilasifen.application.jobs.service import JobService

router = APIRouter(tags=["jobs"])


@router.get(
    "/emitters/{emitter_id}/jobs/{job_id}", response_model=JobEnvelope
)
def get_job(
    emitter_id: str,
    job_id: str,
    request: Request,
    _principal=Depends(require_emitter_read),
    service: JobService = Depends(get_job_service),
) -> JobEnvelope:
    job = service.get_job_for_emitter(emitter_id=emitter_id, job_id=job_id)
    return JobEnvelope(
        data=JobData(job=JobResponse.model_validate(job)),
        correlation_id=request.state.correlation_id,
    )


@router.post(
    "/emitters/{emitter_id}/jobs/{job_id}/retry",
    response_model=JobEnvelope,
    description=(
        "Vuelve a encolar un job de documento, evento o webhook del emisor que "
        "no terminó bien: `failed`, trabado en `queued` o `processing` (por "
        "ejemplo, porque se cayó el worker) o con un reintento programado. Es el "
        "mismo reintento del operador en la consola y responde el job en "
        "`queued`. El worker aplica las reglas de siempre: si el documento pudo "
        "llegar al SIFEN, consulta el CDC antes de decidir y sólo reenvía el "
        "mismo XML firmado, así que reintentar no duplica el documento. Nunca "
        "corren dos intentos a la vez: si el job sigue corriendo, vale lo que "
        "decida esa corrida (si termina en `failed`, se puede volver a pedir); "
        "si su worker se cayó, el job vuelve a correr cuando la cola da por "
        "muerta esa corrida, en unos minutos. Un job `succeeded` responde `409`."
    ),
)
def retry_job(
    emitter_id: str,
    job_id: str,
    request: Request,
    _principal=Depends(require_fiscal_write),
    jobs: JobService = Depends(get_job_service),
    admin: AdminConsoleService = Depends(get_admin_service),
) -> JobEnvelope:
    jobs.get_job_for_emitter(emitter_id=emitter_id, job_id=job_id)
    job = admin.retry_job(job_id)
    return JobEnvelope(
        data=JobData(job=JobResponse.model_validate(job)),
        correlation_id=request.state.correlation_id,
    )


@router.get("/jobs", response_model=JobListEnvelope)
def list_jobs(
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    emitter_id: str | None = None,
    status: str | None = None,
    job_type: str | None = None,
    related_entity_type: str | None = None,
    _principal=Depends(get_admin_principal),
    service: JobService = Depends(get_job_service),
) -> JobListEnvelope:
    jobs = service.list_jobs(
        limit=limit,
        offset=offset,
        emitter_id=emitter_id,
        status=status,
        job_type=job_type,
        related_entity_type=related_entity_type,
    )
    return JobListEnvelope(
        data=JobListData(
            jobs=[JobResponse.model_validate(job) for job in jobs],
            pagination=Pagination(limit=limit, offset=offset, count=len(jobs)),
        ),
        correlation_id=request.state.correlation_id,
    )
