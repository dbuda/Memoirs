from celery import Celery

from app.config import get_settings


settings = get_settings()

celery_app = Celery(
    "memoirs",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.tasks"],
)

celery_app.conf.update(
    task_track_started=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_default_retry_delay=5,
    task_max_retries=3,
)


@celery_app.task(name="memoirs.health_check")
def health_check() -> str:
    return "ok"
