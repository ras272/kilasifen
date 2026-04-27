import json
import logging

from kilasifen.logging import JsonLogFormatter, reset_correlation_id, set_correlation_id


def test_json_log_formatter_includes_correlation_id_and_extra_fields() -> None:
    formatter = JsonLogFormatter()
    record = logging.LogRecord(
        name="kila.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="hello",
        args=(),
        exc_info=None,
    )
    record.emitter_id = "emitter-1"
    record.job_id = "job-1"

    token = set_correlation_id("corr-123")
    try:
        payload = json.loads(formatter.format(record))
    finally:
        reset_correlation_id(token)

    assert payload["message"] == "hello"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "kila.test"
    assert payload["correlation_id"] == "corr-123"
    assert payload["emitter_id"] == "emitter-1"
    assert payload["job_id"] == "job-1"

