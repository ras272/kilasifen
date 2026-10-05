"""Inutilization rules (DECISIONES F72) and its event XML (NT 10 §1.7)."""

from datetime import date, datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from kilasifen.application.events.attempts import (
    EventAnswered,
    EventAttempt,
    EventUnresolved,
    run_event_attempt,
)
from kilasifen.domain.events.inutilization import (
    inutilization_deadline,
    is_inutilizable,
)
from kilasifen.engine.sdk.errors import SifenValidationError
from kilasifen.infrastructure.sifen.event import EventSubmissionOutcome
from kilasifen.infrastructure.sifen.typed_event_builder import (
    build_signed_inutilization_event_group_xml,
)

_NS = "{http://ekuatia.set.gov.py/sifen/xsd}"
_PFX = Path(__file__).resolve().parents[1] / "test_cert.pfx"


@pytest.mark.parametrize(
    ("consumed_on", "deadline"),
    [
        (date(2026, 1, 31), date(2026, 2, 15)),
        (date(2026, 2, 1), date(2026, 3, 15)),
        (date(2026, 12, 3), date(2027, 1, 15)),
    ],
)
def test_the_deadline_is_day_15_of_the_next_month(
    consumed_on: date, deadline: date
) -> None:
    # MT v150 §6.2.1 (p. 25) and Tabla J (p. 117); RG 23/2019 Art. 23.
    assert inutilization_deadline(consumed_on) == deadline


@pytest.mark.parametrize(
    ("document_status", "job_status", "expected"),
    [
        ("rejected", "failed", True),
        ("failed", "failed", True),
        ("queued", "failed", True),
        ("queued", None, True),
        ("queued", "retry_scheduled", False),
        ("rejected", "retry_scheduled", False),
        ("failed", "queued", False),
        ("approved", "succeeded", False),
        ("approved_with_observation", "succeeded", False),
        ("cancelled", "succeeded", False),
        ("inutilized", "failed", False),
        ("submitting", "processing", False),
        ("retry_pending", "retry_scheduled", False),
        ("reconciliation_required", "failed", False),
    ],
)
def test_which_numbers_may_be_inutilized(
    document_status: str, job_status: str | None, expected: bool
) -> None:
    # A DTE cannot be inutilized (4065, MT v150 §11.6.2 p. 135); a document
    # that may be at SIFEN waits for a query by CDC (0420).
    assert is_inutilizable(document_status, job_status) is expected


def _inutilization_xml(**overrides) -> str:
    if not _PFX.exists():
        pytest.skip("tests/test_cert.pfx no existe")
    arguments = {
        "timbrado": "12345678",
        "i_tide": 1,
        "establishment": "1",
        "point": "1",
        "numero_desde": 1,
        "numero_hasta": 3,
        "motivo": "Saltos de numeracion",
        "signed_at": datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc),
        "event_id": "124",
        "certificate_bytes": _PFX.read_bytes(),
        "certificate_password": "test1234",
    }
    arguments.update(overrides)
    return build_signed_inutilization_event_group_xml(**arguments)


def test_the_series_travels_as_dSerieNum_after_the_motive() -> None:
    xml = _inutilization_xml(serie="AB")

    group = ET.fromstring(xml.encode("utf-8")).find(f".//{_NS}rGeVeInu")
    assert group is not None
    assert [child.tag.replace(_NS, "") for child in group][-2:] == [
        "mOtEve",
        "dSerieNum",
    ]
    assert group.find(f"{_NS}dSerieNum").text == "AB"


def test_without_series_no_dSerieNum_is_written() -> None:
    xml = _inutilization_xml()

    assert "dSerieNum" not in xml


@pytest.mark.parametrize("serie", ["A", "ab", "A1", "ABC"])
def test_an_invalid_series_is_refused(serie: str) -> None:
    with pytest.raises(SifenValidationError, match="invalid_serie"):
        _inutilization_xml(serie=serie)


class _Answering:
    def __init__(self, code: str) -> None:
        self.code = code

    def submit_prepared(self, **kwargs) -> EventSubmissionOutcome:
        del kwargs
        return EventSubmissionOutcome(
            response_raw="<rRetEnviEventoDe/>",
            status="rejected",
            result_code=self.code,
            result_message="Existen numeros de DE ya inutilizados en SIFEN",
            protocol=None,
        )


def _attempt(*, after_uncertain_attempt: bool) -> EventAttempt:
    return EventAttempt(
        job_id="job-1",
        event_id="event-1",
        attempt_number=2,
        request_xml="<rEnviEventoDe/>",
        emitter=None,
        certificate_bytes=b"",
        certificate_password="",
        event_type="inutilize_numbers",
        after_uncertain_attempt=after_uncertain_attempt,
    )


def test_4066_after_an_uncertain_attempt_is_left_to_an_operator() -> None:
    # No service tells whether the earlier attempt registered the range
    # (NO DETERMINADO): 4066 is not read as a rejection then.
    result = run_event_attempt(
        _Answering("4066"), None, _attempt(after_uncertain_attempt=True)
    )

    assert isinstance(result, EventUnresolved)


def test_4066_on_a_first_attempt_is_a_rejection() -> None:
    result = run_event_attempt(
        _Answering("4066"), None, _attempt(after_uncertain_attempt=False)
    )

    assert isinstance(result, EventAnswered)
    assert result.outcome.status == "rejected"
