"""Guards for deployment artifacts that no runtime test exercises.

PyYAML is not a dependency of the project, so these checks read the YAML files
as indented text. They rely only on the block layout used in this repository:
a key on its own line followed by the lines nested under it.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ".github/workflows/tests.yml"
NON_HTTP_COMPOSE_SERVICES = ("worker", "outbox", "migrate")


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _block(text: str, header: str) -> str:
    """Return the lines nested under the first ``header`` line.

    A trailing ``# comment`` on the header line is ignored when matching.
    """

    lines = text.splitlines()
    start = [line.split(" #", 1)[0].rstrip() for line in lines].index(header)
    indent = len(header) - len(header.lstrip())
    body: list[str] = []
    for line in lines[start + 1 :]:
        stripped = line.strip()
        is_content = bool(stripped) and not stripped.startswith("#")
        if is_content and len(line) - len(line.lstrip()) <= indent:
            break
        body.append(line)
    return "\n".join(body)


@pytest.mark.parametrize("service", NON_HTTP_COMPOSE_SERVICES)
def test_compose_disables_the_http_healthcheck_for_non_http_services(
    service: str,
) -> None:
    service_block = _block(_read("docker-compose.yml"), f"  {service}:")

    healthcheck = _block(service_block, "    healthcheck:")

    assert "      disable: true" in healthcheck.splitlines()


def test_compose_api_keeps_the_image_healthcheck_on_liveness() -> None:
    api_block = _block(_read("docker-compose.yml"), "  api:")

    assert "    healthcheck:" not in api_block.splitlines()
    assert re.search(
        r"^HEALTHCHECK .*\\\n\s+CMD .*/v1/health",
        _read("Dockerfile"),
        flags=re.MULTILINE,
    )


def test_compose_redis_persists_queued_jobs_across_restarts() -> None:
    compose = _read("docker-compose.yml")
    redis_block = _block(compose, "  redis:")

    assert '"--appendonly", "yes"' in redis_block
    assert "      - kila-redis-data:/data" in redis_block.splitlines()
    assert "  kila-redis-data:" in _block(compose, "volumes:").splitlines()


def test_ci_runs_on_pull_requests_to_any_branch() -> None:
    triggers = _block(_read(WORKFLOW), "on:")

    assert _block(triggers, "  pull_request:").strip() == ""
    assert _block(triggers, "  push:").split() == ["branches:", "[main]"]
    assert "cron:" in _block(triggers, "  schedule:")


def test_ci_platform_job_runs_every_nested_test_package() -> None:
    platform_job = _block(_read(WORKFLOW), "  platform-tests:")
    pytest_commands = [
        line.split()
        for line in platform_job.splitlines()
        if line.split()[:3] == ["uv", "run", "pytest"]
    ]
    nested_test_packages = {
        f"tests/{directory.name}"
        for directory in (ROOT / "tests").iterdir()
        if directory.is_dir() and any(directory.rglob("test_*.py"))
    }

    assert len(pytest_commands) == 1
    selected = {arg for arg in pytest_commands[0] if arg.startswith("tests/")}
    assert selected == nested_test_packages
