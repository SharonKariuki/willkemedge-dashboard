"""Tests for the daily IPN reconciliation summary + HTTP trigger."""
import datetime as dt
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.payments.models import CoopIpnEvent, CoopIpnStatus
from apps.payments.reconciliation import (
    build_daily_reconciliation_summary,
    render_summary_sms,
    render_summary_text,
)

TRIGGER_URL = "/api/payments/coop/reconcile-daily/"
TRIGGER_TOKEN = "test-recon-token-456"


def _yesterday_noon():
    """Midday on the day the summary defaults to, in the project timezone.

    The summary window is built from `timezone.localdate()`, and Nairobi is
    three hours ahead of UTC. A timestamp derived from `timezone.now()` keeps
    the UTC date, so between midnight and 03:00 EAT it lands a full day before
    the window and the summary sees no events at all — the whole file went red
    on any CI run in that hour.
    """
    target = timezone.localdate() - dt.timedelta(days=1)
    return timezone.make_aware(dt.datetime.combine(target, dt.time(hour=12)))


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture(autouse=True)
def _trigger_token(settings):
    settings.RECONCILIATION_TRIGGER_TOKEN = TRIGGER_TOKEN


@pytest.mark.django_db
def test_summary_aggregates_by_status_and_total():
    # auto_now_add doesn't let us pass received_at on .create, so we backdate.
    yesterday = _yesterday_noon()
    e1 = CoopIpnEvent.objects.create(
        transaction_id="T1", amount=Decimal("1000"),
        status=CoopIpnStatus.RECORDED, raw_payload={},
    )
    e2 = CoopIpnEvent.objects.create(
        transaction_id="T2", amount=Decimal("500"),
        status=CoopIpnStatus.RECORDED, raw_payload={},
    )
    e3 = CoopIpnEvent.objects.create(
        transaction_id="T3", amount=Decimal("200"),
        status=CoopIpnStatus.UNMATCHED, raw_payload={},
    )
    e4 = CoopIpnEvent.objects.create(
        transaction_id="T4", amount=Decimal("100"),
        status=CoopIpnStatus.IGNORED, raw_payload={},
    )
    CoopIpnEvent.objects.filter(pk__in=[e1.pk, e2.pk, e3.pk, e4.pk]).update(received_at=yesterday)

    summary = build_daily_reconciliation_summary()  # defaults to yesterday

    assert summary["total_count"] == 4
    assert summary["total_amount"] == Decimal("1800.00")
    assert summary["needs_attention"] == 1  # only the UNMATCHED counts here
    assert summary["by_status"][CoopIpnStatus.RECORDED]["count"] == 2
    assert summary["by_status"][CoopIpnStatus.RECORDED]["total"] == Decimal("1500.00")
    assert summary["by_status"][CoopIpnStatus.UNMATCHED]["count"] == 1


@pytest.mark.django_db
def test_summary_text_handles_empty_day():
    summary = build_daily_reconciliation_summary()  # no events
    body = render_summary_text(summary)
    assert "No rent payments came in" in body
    assert "Wilkem Edge" in body


@pytest.mark.django_db
def test_summary_text_uses_plain_language_no_jargon():
    yesterday = _yesterday_noon()
    e1 = CoopIpnEvent.objects.create(
        transaction_id="TX1", amount=Decimal("20000"),
        status=CoopIpnStatus.RECORDED, raw_payload={},
    )
    e2 = CoopIpnEvent.objects.create(
        transaction_id="TX2", amount=Decimal("500"),
        status=CoopIpnStatus.UNMATCHED, raw_payload={},
    )
    CoopIpnEvent.objects.filter(pk__in=[e1.pk, e2.pk]).update(received_at=yesterday)
    body = render_summary_text(build_daily_reconciliation_summary())
    # friendly labels, not internal status names
    assert "Matched to a tenant and recorded" in body
    assert "Could not be auto-matched" in body
    assert "needs your attention" in body
    # no internal jargon leaks through
    assert "RECORDED" not in body
    assert "UNMATCHED" not in body
    assert "IPN" not in body


@pytest.mark.django_db
def test_summary_sms_flags_needs_attention():
    yesterday = _yesterday_noon()
    ev = CoopIpnEvent.objects.create(
        transaction_id="TX", amount=Decimal("500"),
        status=CoopIpnStatus.REVERSAL_PENDING, raw_payload={},
    )
    CoopIpnEvent.objects.filter(pk=ev.pk).update(received_at=yesterday)
    sms = render_summary_sms(build_daily_reconciliation_summary())
    assert "needs your attention" in sms


@pytest.mark.django_db
def test_summary_sms_all_clear_when_nothing_pending():
    yesterday = _yesterday_noon()
    ev = CoopIpnEvent.objects.create(
        transaction_id="TXOK", amount=Decimal("20000"),
        status=CoopIpnStatus.RECORDED, raw_payload={},
    )
    CoopIpnEvent.objects.filter(pk=ev.pk).update(received_at=yesterday)
    sms = render_summary_sms(build_daily_reconciliation_summary())
    assert "All clear" in sms


# ── HTTP trigger ───────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_trigger_rejects_missing_token(api_client):
    resp = api_client.get(TRIGGER_URL)
    assert resp.status_code == 401


@pytest.mark.django_db
def test_trigger_rejects_wrong_token(api_client):
    resp = api_client.get(TRIGGER_URL + "?token=WRONG")
    assert resp.status_code == 401


@pytest.mark.django_db
@patch("apps.payments.reconciliation_views.send_daily_reconciliation")
def test_trigger_accepts_query_token_and_runs(mock_task, api_client):
    mock_task.apply.return_value.get.return_value = None
    resp = api_client.get(TRIGGER_URL + f"?token={TRIGGER_TOKEN}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    mock_task.apply.assert_called_once_with(args=(None,))


@pytest.mark.django_db
@patch("apps.payments.reconciliation_views.send_daily_reconciliation")
def test_trigger_accepts_bearer_header_and_date(mock_task, api_client):
    mock_task.apply.return_value.get.return_value = None
    resp = api_client.get(
        TRIGGER_URL + "?date=2026-05-30",
        HTTP_AUTHORIZATION=f"Bearer {TRIGGER_TOKEN}",
    )
    assert resp.status_code == 200
    assert resp.json()["date"] == "2026-05-30"
    mock_task.apply.assert_called_once_with(args=("2026-05-30",))
