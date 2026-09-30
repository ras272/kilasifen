from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from kilasifen.domain.sandbox import SandboxOutcome
from kilasifen.engine.sdk.errors import SifenTimeoutError
from kilasifen.infrastructure.sandbox.transport import DeterministicSandboxTransport
from kilasifen.infrastructure.sifen.engine import PysifenEmissionEngine


@pytest.mark.parametrize(
    ("forced_outcome", "expected_status", "expected_code"),
    [
        (SandboxOutcome.APPROVED, "approved", "0260"),
        (
            SandboxOutcome.APPROVED_WITH_OBSERVATION,
            "approved_with_observation",
            "0260",
        ),
        (SandboxOutcome.REJECTED, "rejected", "1330"),
    ],
)
def test_sandbox_transport_forces_outcome_without_live_sifen(
    forced_outcome: SandboxOutcome,
    expected_status: str,
    expected_code: str,
) -> None:
    mapper = Mock()
    mapper.map_document.return_value = SimpleNamespace(
        generated_xml='<rDE><DE Id="0180012345"/></rDE>',
        signed_xml='<rDE><DE Id="0180012345"/><Signature/></rDE>',
        doc_id="0180012345",
    )
    engine = PysifenEmissionEngine(
        mapper=mapper,
        deployment_environment="test",
        transport=DeterministicSandboxTransport(
            runtime_environment="test",
            outcome=forced_outcome,
        ),
    )

    result = engine.emit_document(
        document=Mock(),
        emitter=SimpleNamespace(tax_environment="test"),
        certificate=Mock(),
        certificate_bytes=b"not-used-by-sandbox",
        certificate_password="not-used-by-sandbox",
        stamping=Mock(),
    )

    assert result.sifen_status == expected_status
    assert result.result_code == expected_code
    assert result.cdc == "0180012345"
    assert f"<outcome>{forced_outcome.value}</outcome>" in result.response_raw


@pytest.mark.parametrize(
    ("forced_outcome", "expected_message"),
    [
        (SandboxOutcome.TRANSPORT_TIMEOUT, "timeout de transporte"),
        (
            SandboxOutcome.ACCEPTED_BUT_RESPONSE_LOST,
            "acepto el DE pero se perdio la respuesta",
        ),
    ],
)
def test_sandbox_transport_simulates_ambiguous_transport_failures(
    forced_outcome: SandboxOutcome,
    expected_message: str,
) -> None:
    transport = DeterministicSandboxTransport(
        runtime_environment="test",
        outcome=forced_outcome,
    )

    with pytest.raises(SifenTimeoutError, match=expected_message):
        transport.submit(
            signed_xml="<rDE/>",
            tax_environment="test",
            certificate_bytes=b"unused",
            certificate_password="unused",
        )


@pytest.mark.parametrize("environment", ["development", "staging", "production"])
def test_sandbox_transport_cannot_be_constructed_outside_test(
    environment: str,
) -> None:
    with pytest.raises(ValueError, match="environment=test"):
        DeterministicSandboxTransport(
            runtime_environment=environment,
            outcome=SandboxOutcome.APPROVED,
        )


def test_sandbox_transport_refuses_production_emitter() -> None:
    transport = DeterministicSandboxTransport(
        runtime_environment="test",
        outcome=SandboxOutcome.APPROVED,
    )

    with pytest.raises(ValueError, match="test emitter"):
        transport.submit(
            signed_xml="<rDE/>",
            tax_environment="production",
            certificate_bytes=b"unused",
            certificate_password="unused",
        )
