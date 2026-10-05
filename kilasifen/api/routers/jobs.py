"""Job API routes."""

from fastapi import APIRouter, Depends, Query, Request

from kilasifen.api.deps import (
    get_admin_principal,
    get_job_service,
    require_emitter_read,
)
from kilasifen.api.schemas.common import Pagination
from kilasifen.api.schemas.jobs import (
    JobData,
    JobEnvelope,
    JobListData,
    JobListEnvelope,
    JobResponse,
)
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
