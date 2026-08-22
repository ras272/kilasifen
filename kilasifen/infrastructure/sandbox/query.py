"""Deterministic read-side SIFEN behavior for ambiguous sandbox scenarios."""

from kilasifen.domain.emitters.models import Emitter
from kilasifen.domain.sandbox import SandboxOutcome
from kilasifen.infrastructure.sifen.query import (
    DocumentQueryOutcome,
    RucQueryOutcome,
)


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
            return DocumentQueryOutcome(
                cdc=cdc,
                request_xml=_query_xml(cdc),
                response_raw=_response_xml("found", cdc),
                result_code="0422",
                result_message="Sandbox: CDC encontrado y aprobado",
                status="found",
                content_xml=f'<rDE><DE Id="{cdc}"/><Signature/></rDE>',
                processed_at=None,
            )

        return DocumentQueryOutcome(
            cdc=cdc,
            request_xml=_query_xml(cdc),
            response_raw=_response_xml("not_found", cdc),
            result_code="0420",
            result_message="Sandbox: CDC no encontrado o no aprobado",
            status="not_found",
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
