"""Tests for ADMIN_ALERTS_ENABLED — the internal staff-alert master switch.

Companion to TENANT_NOTIFICATIONS_ENABLED. Together they give a fully silent
testing window: tenants hear nothing, staff hear nothing, and the ledger keeps
being written.
"""
import datetime as dt
from decimal import Decimal
from unittest.mock import patch

import pytest

from apps.payments.models import CoopIpnEvent, CoopIpnStatus
from apps.payments.tasks import (
    send_daily_reconciliation,
    send_reversal_authorization_alert,
    send_unmatched_credit_alert,
)


@pytest.fixture(autouse=True)
def _contacts(settings):
    settings.ADMIN_ALERT_PHONE = "+254700000001"
    settings.ADMIN_ALERT_EMAIL = "admin@wilkem.test"
    settings.DIRECTOR_ALERT_PHONE = "+254722527234"
    settings.DIRECTOR_ALERT_EMAIL = "director@wilkem.test"
    settings.AT_API_KEY = ""


@pytest.fixture
def unmatched_event(db):
    return CoopIpnEvent.objects.create(
        transaction_id="TXN-ADMIN-1", amount=Decimal("7500"),
        status=CoopIpnStatus.UNMATCHED, detail="No unit matched", raw_payload={},
    )


@pytest.fixture
def reversal_event(db):
    return CoopIpnEvent.objects.create(
        transaction_id="TXN-REV-1", amount=Decimal("4200"),
        status=CoopIpnStatus.UNMATCHED, detail="Reversal notified", raw_payload={},
    )


@pytest.mark.django_db
def test_unmatched_alert_suppressed(settings, unmatched_event):
    settings.ADMIN_ALERTS_ENABLED = False
    with patch("apps.payments.notifications.send_sms") as sms, \
            patch("apps.payments.notifications.send_email") as email:
        send_unmatched_credit_alert(unmatched_event.id)

    sms.assert_not_called()
    email.assert_not_called()


@pytest.mark.django_db
def test_unmatched_alert_fires_when_enabled(settings, unmatched_event):
    settings.ADMIN_ALERTS_ENABLED = True
    with patch("apps.payments.notifications.send_sms") as sms, \
            patch("apps.payments.notifications.send_email"):
        send_unmatched_credit_alert(unmatched_event.id)

    assert sms.call_count == 2  # admin + director


@pytest.mark.django_db
def test_daily_summary_suppressed(settings):
    settings.ADMIN_ALERTS_ENABLED = False
    yesterday = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    with patch("apps.payments.notifications.send_sms") as sms, \
            patch("apps.payments.notifications.send_email") as email:
        send_daily_reconciliation(yesterday)

    sms.assert_not_called()
    email.assert_not_called()


@pytest.mark.django_db
def test_reversal_alert_suppressed_but_logged_loudly(settings, reversal_event, caplog):
    """Money leaving the account — suppression must be visible in the logs."""
    settings.ADMIN_ALERTS_ENABLED = False
    with patch("apps.payments.notifications.send_sms") as sms, \
            patch("apps.payments.notifications.send_email") as email:
        with caplog.at_level("WARNING"):
            send_reversal_authorization_alert(reversal_event.id)

    sms.assert_not_called()
    email.assert_not_called()
    assert any(
        "SUPPRESSED" in r.message or "SUPPRESSED" in r.getMessage()
        for r in caplog.records
    )


@pytest.mark.django_db
def test_reversal_alert_fires_when_enabled(settings, reversal_event):
    settings.ADMIN_ALERTS_ENABLED = True
    with patch("apps.payments.notifications.send_sms") as sms, \
            patch("apps.payments.notifications.send_email"):
        send_reversal_authorization_alert(reversal_event.id)

    sms.assert_called_once()


@pytest.mark.django_db
def test_switches_are_independent(settings, unmatched_event):
    """Silencing tenants must not silence staff, and vice versa."""
    settings.TENANT_NOTIFICATIONS_ENABLED = False
    settings.ADMIN_ALERTS_ENABLED = True
    with patch("apps.payments.notifications.send_sms") as sms, \
            patch("apps.payments.notifications.send_email"):
        send_unmatched_credit_alert(unmatched_event.id)

    assert sms.call_count == 2
