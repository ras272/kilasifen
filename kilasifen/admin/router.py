"""Server-rendered admin routes for Kila SIFEN operations."""

from pathlib import Path

from fastapi import APIRouter, Depends, Form, Query, Request, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from kilasifen.api.deps import get_admin_principal, get_admin_service
from kilasifen.application.admin.service import AdminConsoleService

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("", include_in_schema=False)
def admin_root(
    _principal=Depends(get_admin_principal),
) -> RedirectResponse:
    return RedirectResponse(url="/admin/emitters", status_code=status.HTTP_302_FOUND)


@router.get("/emitters", include_in_schema=False)
def emitters_list(
    request: Request,
    _principal=Depends(get_admin_principal),
    service: AdminConsoleService = Depends(get_admin_service),
):
    emitters = service.list_emitters()
    return templates.TemplateResponse(
        request=request,
        name="emitters/list.html",
        context={"emitters": emitters},
    )


@router.get("/emitters/{emitter_id}", include_in_schema=False)
def emitter_detail(
    emitter_id: str,
    request: Request,
    limit: int = Query(default=20, ge=5, le=100),
    _principal=Depends(get_admin_principal),
    service: AdminConsoleService = Depends(get_admin_service),
):
    detail = service.get_emitter_detail(emitter_id, limit=limit)
    return templates.TemplateResponse(
        request=request,
        name="emitter_detail.html",
        context={"detail": detail, "limit": limit},
    )


@router.get("/documents", include_in_schema=False)
def documents_list(
    request: Request,
    emitter_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=5, le=200),
    _principal=Depends(get_admin_principal),
    service: AdminConsoleService = Depends(get_admin_service),
):
    documents = service.list_documents(limit=limit, emitter_id=emitter_id)
    return templates.TemplateResponse(
        request=request,
        name="documents/list.html",
        context={
            "documents": documents,
            "emitter_id": emitter_id,
            "limit": limit,
        },
    )


@router.get("/jobs", include_in_schema=False)
def jobs_list(
    request: Request,
    emitter_id: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=5, le=200),
    _principal=Depends(get_admin_principal),
    service: AdminConsoleService = Depends(get_admin_service),
):
    jobs = service.list_jobs(limit=limit, emitter_id=emitter_id, status=status_filter)
    return templates.TemplateResponse(
        request=request,
        name="jobs/list.html",
        context={
            "jobs": jobs,
            "emitter_id": emitter_id,
            "status_filter": status_filter,
            "limit": limit,
        },
    )


@router.get("/webhooks", include_in_schema=False)
def webhooks_list(
    request: Request,
    emitter_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=5, le=200),
    _principal=Depends(get_admin_principal),
    service: AdminConsoleService = Depends(get_admin_service),
):
    rows = service.list_failed_webhook_deliveries(limit=limit, emitter_id=emitter_id)
    return templates.TemplateResponse(
        request=request,
        name="webhooks/list.html",
        context={"rows": rows, "emitter_id": emitter_id, "limit": limit},
    )


@router.post("/certificates/{certificate_id}/activate", include_in_schema=False)
def activate_certificate(
    certificate_id: str,
    _request: Request,
    next_url: str = Form(default="/admin/emitters"),
    _principal=Depends(get_admin_principal),
    service: AdminConsoleService = Depends(get_admin_service),
) -> RedirectResponse:
    certificate = service.activate_certificate(certificate_id)
    fallback = f"/admin/emitters/{certificate.emitter_id}"
    return RedirectResponse(
        url=_safe_next(next_url, fallback=fallback),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/jobs/{job_id}/retry", include_in_schema=False)
def retry_job(
    job_id: str,
    _request: Request,
    next_url: str = Form(default="/admin/jobs"),
    _principal=Depends(get_admin_principal),
    service: AdminConsoleService = Depends(get_admin_service),
) -> RedirectResponse:
    job = service.retry_job(job_id)
    fallback = f"/admin/jobs?emitter_id={job.emitter_id}" if job.emitter_id else "/admin/jobs"
    return RedirectResponse(
        url=_safe_next(next_url, fallback=fallback),
        status_code=status.HTTP_303_SEE_OTHER,
    )


def _safe_next(next_url: str, *, fallback: str) -> str:
    if next_url.startswith("/admin"):
        return next_url
    return fallback

