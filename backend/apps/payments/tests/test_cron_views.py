"""Tests for the HTTP cron triggers that stand in for Celery beat."""
from unittest.mock import patch

import pytest
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.payments import tasks

TOKEN = "s3cret-cron-token"


@pytest.fixture
def client():
    return APIClient()


def url(job: str) -> str:
    return reverse("payments:cron-job", kwargs={"job": job})


# JOBS holds direct references to the task objects, so the task's own .apply is
# what has to be patched — rebinding the module attribute would not be seen.
def stub(task):
    return patch.object(task, "apply")


@pytest.mark.django_db
@override_settings(CRON_TRIGGER_TOKEN=TOKEN)
@pytest.mark.parametrize(
    "job,task",
    [
        ("rent-reminders", tasks.send_rent_reminders),
        ("arrears-reminders", tasks.send_arrears_reminders),
        ("recalculate-statuses", tasks.recalculate_all_statuses),
        ("monthly-arrears", tasks.generate_monthly_arrears),
        ("daily-reconciliation", tasks.send_daily_reconciliation),
    ],
)
def test_each_job_runs_with_a_valid_token(client, job, task):
    with stub(task) as apply:
        apply.return_value.get.return_value = None
        res = client.post(f"{url(job)}?token={TOKEN}")

    assert res.status_code == 200
    assert res.json()["job"] == job
    apply.assert_called_once()


@pytest.mark.django_db
@override_settings(CRON_TRIGGER_TOKEN=TOKEN)
def test_bearer_header_is_accepted(client):
    with stub(tasks.send_rent_reminders) as apply:
        apply.return_value.get.return_value = 0
        res = client.post(url("rent-reminders"), HTTP_AUTHORIZATION=f"Bearer {TOKEN}")

    assert res.status_code == 200
    apply.assert_called_once()


@pytest.mark.django_db
@override_settings(CRON_TRIGGER_TOKEN=TOKEN)
def test_daily_reconciliation_passes_the_date_through(client):
    with stub(tasks.send_daily_reconciliation) as apply:
        apply.return_value.get.return_value = None
        client.post(f"{url('daily-reconciliation')}?token={TOKEN}&date=2026-07-01")

    apply.assert_called_once_with(args=("2026-07-01",))


@pytest.mark.django_db
@override_settings(CRON_TRIGGER_TOKEN=TOKEN)
@pytest.mark.parametrize("query", ["", "?token=wrong-token"])
def test_a_bad_or_missing_token_runs_nothing(client, query):
    with stub(tasks.send_rent_reminders) as apply:
        res = client.post(f"{url('rent-reminders')}{query}")

    assert res.status_code == 401
    apply.assert_not_called()


@pytest.mark.django_db
@override_settings(CRON_TRIGGER_TOKEN="", RECONCILIATION_TRIGGER_TOKEN="")
def test_no_token_configured_rejects_everything(client):
    """An unset secret must fail closed, not wave every caller through."""
    with stub(tasks.send_rent_reminders) as apply:
        res = client.post(f"{url('rent-reminders')}?token=")

    assert res.status_code == 401
    apply.assert_not_called()


@pytest.mark.django_db
@override_settings(CRON_TRIGGER_TOKEN=TOKEN)
def test_unknown_job_is_404_and_lists_the_valid_jobs(client):
    res = client.post(f"{url('rm-rf')}?token={TOKEN}")

    assert res.status_code == 404
    assert "rent-reminders" in res.json()["jobs"]


@pytest.mark.django_db
@override_settings(CRON_TRIGGER_TOKEN="", RECONCILIATION_TRIGGER_TOKEN=TOKEN)
def test_legacy_reconciliation_token_still_works(client):
    """A scheduler already configured with the old secret must keep working."""
    with stub(tasks.send_daily_reconciliation) as apply:
        apply.return_value.get.return_value = None
        res = client.post(f"{url('daily-reconciliation')}?token={TOKEN}")

    assert res.status_code == 200
