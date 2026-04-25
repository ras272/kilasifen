from rq.timeouts import TimerDeathPenalty

from kilasifen.infrastructure.jobs.worker_classes import CrossPlatformSimpleWorker


def test_cross_platform_simple_worker_uses_timer_death_penalty() -> None:
    assert CrossPlatformSimpleWorker.death_penalty_class is TimerDeathPenalty

