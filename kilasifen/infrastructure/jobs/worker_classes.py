"""Custom RQ worker classes for local/runtime portability."""

from rq import SimpleWorker
from rq.timeouts import TimerDeathPenalty


class CrossPlatformSimpleWorker(SimpleWorker):
    """Simple worker that avoids Unix-only timeout signals on Windows."""

    death_penalty_class = TimerDeathPenalty

