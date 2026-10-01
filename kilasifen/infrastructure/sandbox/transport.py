"""Network-free SIFEN transport with deterministic test outcomes."""

from kilasifen.domain.sandbox import SandboxOutcome
from kilasifen.engine.sdk.errors import SifenTimeoutError
from kilasifen.infrastructure.sifen.engine import SubmissionOutcome

_OUTCOMES = {
    SandboxOutcome.APPROVED: (
        "approved",
        "0260",
        "Sandbox: autorizacion satisfactoria",
    ),
    SandboxOutcome.APPROVED_WITH_OBSERVATION: (
        "approved_with_observation",
        "0260",
        "Sandbox: aprobado con observacion",
    ),
    SandboxOutcome.REJECTED: (
        "rejected",
        "1330",
        "Sandbox: rechazo fiscal forzado",
    ),
}


class DeterministicSandboxTransport:
    """Produce one configured outcome without opening a network connection."""

    def __init__(self, *, runtime_environment: str, outcome: SandboxOutcome):
        if runtime_environment != "test":
            raise ValueError(
                "deterministic sandbox transport requires environment=test"
            )
        self.outcome = outcome

    def submit(
        self,
        *,
        request_xml: str,
        tax_environment: str,
        certificate_bytes: bytes,
        certificate_password: str,
    ) -> SubmissionOutcome:
        del request_xml, certificate_bytes, certificate_password
        if tax_environment != "test":
            raise ValueError("deterministic sandbox transport requires a test emitter")

        if self.outcome is SandboxOutcome.TRANSPORT_TIMEOUT:
            raise SifenTimeoutError("Sandbox: timeout de transporte antes de responder")
        if self.outcome is SandboxOutcome.ACCEPTED_BUT_RESPONSE_LOST:
            raise SifenTimeoutError(
                "Sandbox: SIFEN acepto el DE pero se perdio la respuesta"
            )

        status, code, message = _OUTCOMES[self.outcome]
        response_raw = (
            '<sandboxSifenResponse version="1">'
            f"<outcome>{self.outcome.value}</outcome>"
            f"<code>{code}</code>"
            f"<message>{message}</message>"
            "</sandboxSifenResponse>"
        )
        return SubmissionOutcome(
            response_raw=response_raw,
            sifen_status=status,
            result_code=code,
            result_message=message,
        )
