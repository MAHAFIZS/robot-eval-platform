import os
from celery import Celery

def broker_url() -> str:
    return os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")

def backend_url() -> str:
    return os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")

celery_app = Celery(
    "robot_eval_worker",
    broker=broker_url(),
    backend=backend_url(),
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)

# Autodiscover tasks
celery_app.autodiscover_tasks(["packages.worker"])
