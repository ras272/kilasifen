"""Job API routes."""

from fastapi import APIRouter, Depends, Request

from kilasifen.api.deps import get_api_key_principal, get_job_service
from kilasifen.api.schemas.common import SuccessEnvelope
from kilasifen.api.schemas.jobs import JobResponse
from kilasifen.application.jobs.service import JobService

router = APIRouter(tags=["jobs"])


@router.get("/emitters/{emitter_id}/jobs/{job_id}", response_model=SuccessEnvelope)
def get_job(
    emitter_id: str,
    job_id: str,
    request: Request,
    _principal=Depends(get_api_key_principal),
    service: JobService = Depends(get_job_service),
) -> SuccessEnvelope:
    job = service.get_job_for_emitter(emitter_id=emitter_id, job_id=job_id)
    return SuccessEnvelope(
        data={"job": JobResponse.model_validate(job).model_dump(mode="json")},
        correlation_id=request.state.correlation_id,
    )


@router.get("/jobs", response_model=SuccessEnvelope)
def list_jobs(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    # TODO(multi-tenant): require emitter scoping by principal when opening API to multiple tenants.
    emitter_id: str | None = None,
    status: str | None = None,
    job_type: str | None = None,
    related_entity_type: str | None = None,
    _principal=Depends(get_api_key_principal),
    service: JobService = Depends(get_job_service),
) -> SuccessEnvelope:
    jobs = service.list_jobs(
        limit=limit,
        offset=offset,
        emitter_id=emitter_id,
        status=status,
        job_type=job_type,
        related_entity_type=related_entity_type,
    )
    return SuccessEnvelope(
        data={
            "jobs": [JobResponse.model_validate(job).model_dump(mode="json") for job in jobs],
            "pagination": {"limit": limit, "offset": offset, "count": len(jobs)},
        },
        correlation_id=request.state.correlation_id,
    )
