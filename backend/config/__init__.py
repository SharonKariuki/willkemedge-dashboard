"""
Ensure the Celery app is loaded at Django startup so that
@shared_task tasks resolve to our configured app (with broker, namespace,
and CELERY_TASK_ALWAYS_EAGER settings) instead of Celery's default.
"""
from celery_app import app as celery_app

__all__ = ("celery_app",)
