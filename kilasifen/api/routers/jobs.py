"""Job API routes."""

from fastapi import APIRouter, Depends, Request

from kilasifen.api.deps import get_api_key_principal, get_job_service
from kilasifen.api.schemas.common import SuccessEnvelope
from kilasifen.api.schemas.jobs import JobResponse
from kilasifen.application.jobs.service import JobService

router = APIRouter(tags=["jobs"])


@router.get("/jobs/{job_id}", response_model=SuccessEnvelope)
def get_job(
    job_id: str,
    request: Request,
    _principal=Depends(get_api_key_principal),
    service: JobService = Depends(get_job_service),
) -> SuccessEnvelope:
    job = service.get_job(job_id)
    return SuccessEnvelope(
        data={"job": JobResponse.model_validate(job).model_dump(mode="json")},
        correlation_id=request.state.correlation_id,
    )
