from celery import Celery

from csre.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "csre",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "csre.tasks.reconciliation",
        "csre.tasks.rewards",
    ],
)

celery_app.conf.update(
    task_default_queue="csre",
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
)

