"""Celery application wired to Redis (slide 11: Async Worker/Queue)."""
from celery import Celery

from app.core.config import settings

celery_app = Celery("auditable_automation", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_acks_late=True,          # slide 9: "failures are persisted"
    worker_prefetch_multiplier=1,  # don't starve other jobs on a slow doc
    task_track_started=True,
)

import app.workers.tasks  # noqa: F401 — ensures Celery discovers the task
