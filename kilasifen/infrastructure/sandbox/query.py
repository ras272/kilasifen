"""Deterministic read-side SIFEN behavior for ambiguous sandbox scenarios."""

from kilasifen.domain.emitters.models import Emitter
from kilasifen.domain.sandbox import SandboxOutcome
from kilasifen.infrastructure.sifen.query import (
    QUERY_FOUND,
    QUERY_NOT_FOUND_OR_NOT_APPROVED,
    DocumentQueryOutcome,
    RucQueryOutcome,
)
from kilasifen.infrastructure.sifen.responses import DocumentContainer


class DeterministicSandboxQueryGateway:
    """Resolve sandbox CDC queries without contacting SIFEN."""

    def __init__(self, *, runtime_environment: str, outcome: SandboxOutcome):
        if runtime_environment != "test":
            raise ValueError("deterministic sandbox query requires environment=test")
        self.outcome = outcome

    def query_ruc(
        self,
        *,
        emitter: Emitter,
        certificate_bytes: bytes,
        certificate_password: str,
        ruc: str,
    ) -> RucQueryOutcome:
        del emitter, certificate_bytes, certificate_password, ruc
        raise NotImplementedError("the document sandbox does not simulate RUC queries")

    def query_document(
        self,
        *,
        emitter: Emitter,
        certificate_bytes: bytes,
        certificate_password: str,
        cdc: str,
    ) -> DocumentQueryOutcome:
        del certificate_bytes, certificate_password
        if emitter.tax_environment != "test":
            raise ValueError("deterministic sandbox query requires a test emitter")

        if self.outcome is SandboxOutcome.ACCEPTED_BUT_RESPONSE_LOST:
            content = f'<rDE><DE Id="{cdc}"/><Signature/></rDE>'
            return DocumentQueryOutcome(
                cdc=cdc,
                request_xml=_query_xml(cdc),
                response_raw=_response_xml(QUERY_FOUND, cdc),
                result_code="0422",
                result_message="Sandbox: CDC encontrado y aprobado",
                status=QUERY_FOUND,
                content_xml=content,
                processed_at=None,
                container=DocumentContainer(
                    document_xml=content, protocol=None, events=()
                ),
            )

        return DocumentQueryOutcome(
            cdc=cdc,
            request_xml=_query_xml(cdc),
            response_raw=_response_xml(QUERY_NOT_FOUND_OR_NOT_APPROVED, cdc),
            result_code="0420",
            result_message="Sandbox: CDC no encontrado o no aprobado",
            status=QUERY_NOT_FOUND_OR_NOT_APPROVED,
            content_xml=None,
            processed_at=None,
        )


def _query_xml(cdc: str) -> str:
    return f'<sandboxCdcQuery version="1" cdc="{cdc}"/>'


def _response_xml(status: str, cdc: str) -> str:
    return (
        '<sandboxCdcResponse version="1">'
        f"<cdc>{cdc}</cdc><status>{status}</status>"
        "</sandboxCdcResponse>"
    )
