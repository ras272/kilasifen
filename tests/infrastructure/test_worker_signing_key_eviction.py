"""Signing jobs must not leave decrypted PKCS12 keys in the worker process."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from kilasifen.domain.common.errors import NotFoundError
from kilasifen.engine.sdk.signer import clear_pkcs12_signer_cache, get_pkcs12_signer
from kilasifen.infrastructure.db.base import Base
from kilasifen.infrastructure.db.session import build_engine
from kilasifen.infrastructure.jobs.workers import (
    process_document_job,
    process_event_job,
)
from kilasifen.testing.database import managed_test_database_url

_TEST_CERTIFICATE = Path(__file__).resolve().parents[1] / "test_cert.pfx"
_TEST_PASSWORD = "test1234"


@pytest.fixture
def cached_signer() -> Iterator[object]:
    clear_pkcs12_signer_cache()
    signer = get_pkcs12_signer(_TEST_CERTIFICATE.read_bytes(), _TEST_PASSWORD)
    yield signer
    clear_pkcs12_signer_cache()


@pytest.mark.parametrize("job_function", [process_document_job, process_event_job])
def test_signing_jobs_drop_cached_keys_even_when_they_fail(
    tmp_path,
    cached_signer: object,
    job_function,
) -> None:
    with managed_test_database_url(
        tmp_path=tmp_path, name="signer_eviction"
    ) as database_url:
        Base.metadata.create_all(build_engine(database_url))

        with pytest.raises(NotFoundError):
            job_function(
                job_id="missing-job",
                database_url=database_url,
                encryption_key=Fernet.generate_key().decode(),
            )

    assert not _is_cached(cached_signer)


def _is_cached(signer: object) -> bool:
    """The cache returns the same object for the same container and password."""

    return get_pkcs12_signer(_TEST_CERTIFICATE.read_bytes(), _TEST_PASSWORD) is signer

