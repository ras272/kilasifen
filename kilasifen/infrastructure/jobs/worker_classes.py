"""Custom RQ worker classes for local/runtime portability and speed."""

from rq import SimpleWorker, Worker
from rq.timeouts import TimerDeathPenalty

#: XML roots the jobs validate: a DE (documents) and an event request.
_JOB_SCHEMA_ROOTS = ("rDE", "rEnviEventoDe")


class CrossPlatformSimpleWorker(SimpleWorker):
    """Simple worker that avoids Unix-only timeout signals on Windows."""

    death_penalty_class = TimerDeathPenalty


class PreloadedWorker(Worker):
    """Forking worker that loads the job code once, before any job runs.

    RQ runs each job in a fresh fork of the worker and imports the job
    function inside that fork, so every document, event or webhook job paid
    the import of the platform again (about 1 s, measured 2026-10-08) plus
    the XSD compilation. Loaded here, every fork inherits both. Database
    engines and connections are still opened inside each job, never shared
    across forks. Forking needs Linux or macOS: on Windows use
    :class:`CrossPlatformSimpleWorker`.
    """

    def __init__(self, *args, **kwargs) -> None:
        preload_job_runtime()
        super().__init__(*args, **kwargs)


def preload_job_runtime() -> None:
    """Import the job functions and compile the XSD they validate against."""

    import kilasifen.infrastructure.jobs.workers  # noqa: F401
    from kilasifen.engine.sdk.validation import precargar_esquemas

    precargar_esquemas(*_JOB_SCHEMA_ROOTS)

