"""
Celery application configuration.

Workers are started with:
    celery -A celery_app worker --loglevel=info

Beat scheduler (nightly + hourly jobs):
    celery -A celery_app beat --loglevel=info --scheduler django_celery_beat.schedulers:DatabaseScheduler
"""
import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

app = Celery("willkemedge")

# Read config from Django settings, namespace CELERY_
app.config_from_object("django.conf:settings", namespace="CELERY")

# Auto-discover tasks in all INSTALLED_APPS
app.autodiscover_tasks()


# ---------------------------------------------------------------------------
# Periodic task schedule (Celery Beat)
# ---------------------------------------------------------------------------

app.conf.beat_schedule = {
    # Nightly at 00:30 EAT — recalculate all unit statuses
    "nightly-recalculate-statuses": {
        "task": "apps.payments.tasks.recalculate_all_statuses",
        "schedule": crontab(hour=0, minute=30),
    },
    # 1st of each month at 00:05 EAT — create fresh arrears records
    "monthly-generate-arrears": {
        "task": "apps.payments.tasks.generate_monthly_arrears",
        "schedule": crontab(hour=0, minute=5, day_of_month=1),
    },
    # Hourly bank statement poll fallback
    "hourly-bank-poll": {
        "task": "apps.payments.tasks.poll_bank_statement",
        "schedule": crontab(minute=0),
    },
}

app.conf.timezone = "Africa/Nairobi"
