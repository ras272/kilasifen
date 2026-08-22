from copy import deepcopy

import pytest

from kilasifen.application.sandbox.service import SandboxOutcomePolicy
from kilasifen.domain.common.errors import UnprocessableEntityError
from kilasifen.domain.sandbox import SandboxOutcome


def test_policy_persists_a_versioned_directive_without_mutating_payload() -> None:
    payload = {"typed_contract": {"contract": "factura_v1"}}
    original = deepcopy(payload)

    result = SandboxOutcomePolicy("test").apply(
        payload,
        SandboxOutcome.APPROVED_WITH_OBSERVATION,
    )

    assert payload == original
    assert result == {
        **original,
        "sandbox": {
            "version": 1,
            "outcome": "approved_with_observation",
        },
    }


@pytest.mark.parametrize("environment", ["development", "staging", "production"])
def test_policy_rejects_requested_outcomes_outside_test(environment: str) -> None:
    with pytest.raises(UnprocessableEntityError) as exc_info:
        SandboxOutcomePolicy(environment).apply(
            {"typed_contract": {}},
            SandboxOutcome.APPROVED,
        )

    assert exc_info.value.code == "sandbox.test_runtime_required"


def test_policy_removes_untrusted_caller_directive_without_header() -> None:
    result = SandboxOutcomePolicy("test").apply(
        {
            "generated_xml": None,
            "sandbox": {"version": 1, "outcome": "approved"},
        },
        None,
    )

    assert result == {"generated_xml": None}


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_policy_refuses_persisted_directive_outside_test(environment: str) -> None:
    with pytest.raises(UnprocessableEntityError) as exc_info:
        SandboxOutcomePolicy(environment).resolve(
            {"sandbox": {"version": 1, "outcome": "approved"}}
        )

    assert exc_info.value.code == "sandbox.test_runtime_required"

