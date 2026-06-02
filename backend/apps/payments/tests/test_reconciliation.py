"""Tests for the daily IPN reconciliation summary."""
import datetime as dt
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.payments.models import CoopIpnEvent, CoopIpnStatus
from apps.payments.reconciliation import (
    build_daily_reconciliation_summary,
    render_summary_sms,
    render_summary_text,
)


@pytest.mark.django_db
def test_summary_aggregates_by_status_and_total():
    # auto_now_add doesn't let us pass received_at on .create, so we backdate.
    yesterday = (timezone.now() - dt.timedelta(days=1)).replace(hour=12)
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
    assert "Events:  0" in body
    assert "no IPN events received" in body
    assert "KES 0.00" in body


@pytest.mark.django_db
def test_summary_sms_flags_needs_attention():
    yesterday = (timezone.now() - dt.timedelta(days=1)).replace(hour=12)
    ev = CoopIpnEvent.objects.create(
        transaction_id="TX", amount=Decimal("500"),
        status=CoopIpnStatus.REVERSAL_PENDING, raw_payload={},
    )
    CoopIpnEvent.objects.filter(pk=ev.pk).update(received_at=yesterday)
    sms = render_summary_sms(build_daily_reconciliation_summary())
    assert "1 need attention" in sms
