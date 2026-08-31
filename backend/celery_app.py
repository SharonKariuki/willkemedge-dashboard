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
    # 25th at 06:30 EAT — raise NEXT month's rent, ahead of the statement run.
    # See apps/payments/billing_calendar.py for why the cycle runs a month
    # ahead of the calendar. Production has no beat process — the real
    # scheduler is .github/workflows/scheduled-jobs.yml — so these two must be
    # kept in step with it.
    "advance-generate-arrears": {
        "task": "apps.payments.tasks.generate_monthly_arrears",
        "schedule": crontab(hour=6, minute=30, day_of_month=25),
    },
    # 25th at 07:00 EAT — email every tenant next month's statement
    "advance-send-statements": {
        "task": "apps.payments.tasks.send_monthly_statements",
        "schedule": crontab(hour=7, minute=0, day_of_month=25),
    },
    # 1st of each month at 00:05 EAT — catch-up for any month the 25th missed
    "monthly-generate-arrears": {
        "task": "apps.payments.tasks.generate_monthly_arrears",
        "schedule": crontab(hour=0, minute=5, day_of_month=1),
    },
    # Daily at 08:00 EAT — rent reminders N days before each tenant's due day
    "daily-rent-reminders": {
        "task": "apps.payments.tasks.send_rent_reminders",
        "schedule": crontab(hour=8, minute=0),
    },
    # Daily at 09:00 EAT — arrears reminders for unpaid rent past the due day
    "daily-arrears-reminders": {
        "task": "apps.payments.tasks.send_arrears_reminders",
        "schedule": crontab(hour=9, minute=0),
    },
    # Hourly bank statement poll fallback
    "hourly-bank-poll": {
        "task": "apps.payments.tasks.poll_bank_statement",
        "schedule": crontab(minute=0),
    },
}

app.conf.timezone = "Africa/Nairobi"
