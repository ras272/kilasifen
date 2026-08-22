import pytest

from kilasifen.domain.sandbox import SandboxOutcome
from kilasifen.infrastructure.sandbox.query import DeterministicSandboxQueryGateway


class _Emitter:
    tax_environment = "test"


def test_accepted_response_lost_is_found_during_cdc_reconciliation() -> None:
    gateway = DeterministicSandboxQueryGateway(
        runtime_environment="test",
        outcome=SandboxOutcome.ACCEPTED_BUT_RESPONSE_LOST,
    )

    result = gateway.query_document(
        emitter=_Emitter(),
        certificate_bytes=b"unused",
        certificate_password="unused",
        cdc="0180012345",
    )

    assert result.status == "found"
    assert result.result_code == "0422"
    assert result.content_xml is not None
    assert 'Id="0180012345"' in result.content_xml


def test_transport_timeout_remains_ambiguous_during_cdc_reconciliation() -> None:
    gateway = DeterministicSandboxQueryGateway(
        runtime_environment="test",
        outcome=SandboxOutcome.TRANSPORT_TIMEOUT,
    )

    result = gateway.query_document(
        emitter=_Emitter(),
        certificate_bytes=b"unused",
        certificate_password="unused",
        cdc="0180012345",
    )

    assert result.status == "not_found"
    assert result.result_code == "0420"
    assert result.content_xml is None


@pytest.mark.parametrize("environment", ["development", "staging", "production"])
def test_sandbox_query_cannot_be_constructed_outside_test(environment: str) -> None:
    with pytest.raises(ValueError, match="environment=test"):
        DeterministicSandboxQueryGateway(
            runtime_environment=environment,
            outcome=SandboxOutcome.ACCEPTED_BUT_RESPONSE_LOST,
        )


def test_sandbox_query_refuses_production_emitter() -> None:
    gateway = DeterministicSandboxQueryGateway(
        runtime_environment="test",
        outcome=SandboxOutcome.ACCEPTED_BUT_RESPONSE_LOST,
    )
    production_emitter = _Emitter()
    production_emitter.tax_environment = "production"

    with pytest.raises(ValueError, match="test emitter"):
        gateway.query_document(
            emitter=production_emitter,
            certificate_bytes=b"unused",
            certificate_password="unused",
            cdc="0180012345",
        )
