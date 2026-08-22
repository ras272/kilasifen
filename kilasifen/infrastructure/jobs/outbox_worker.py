"""Long-running sweeper that dispatches committed job-outbox rows to RQ."""

import logging
import time

from redis import Redis
from rq import Queue

from kilasifen.config import get_settings
from kilasifen.infrastructure.db.session import build_engine, build_session_factory
from kilasifen.infrastructure.jobs.outbox import JobOutboxDispatcher
from kilasifen.infrastructure.jobs.queue import RqJobQueue
from kilasifen.observability import ensure_worker_observability

logger = logging.getLogger(__name__)

OUTBOX_HEARTBEAT_KEY = "kilasifen:outbox:heartbeat"


def run(*, poll_interval: float = 1.0, heartbeat_ttl: int = 10) -> None:
    """Continuously dispatch the durable outbox until the process is stopped."""

    settings = get_settings()
    ensure_worker_observability()
    redis_connection = Redis.from_url(settings.redis_url)
    session_factory = build_session_factory(build_engine(settings.database_url))
    dispatcher = JobOutboxDispatcher(
        session_factory=session_factory,
        queues={
            name: RqJobQueue(Queue(name, connection=redis_connection))
            for name in ("documents", "events", "webhooks")
        },
    )
    logger.info("jobs.outbox.dispatcher_started")
    while True:
        try:
            redis_connection.set(OUTBOX_HEARTBEAT_KEY, "1", ex=heartbeat_ttl)
            dispatcher.dispatch_once()
        except Exception:
            logger.exception("jobs.outbox.dispatch_cycle_failed")
        time.sleep(poll_interval)


if __name__ == "__main__":
    run()
