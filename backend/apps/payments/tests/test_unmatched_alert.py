"""Tests for the unmatched-credit alert recipients.

An unmatched credit is money already in the bank that no tenant has been
credited for, so the alert must reach both the admin and the director — the
director holds the `owner` role and can clear the queue himself.
"""
from decimal import Decimal
from unittest.mock import patch

import pytest

from apps.payments.models import CoopIpnEvent, CoopIpnStatus
from apps.payments.tasks import send_unmatched_credit_alert

ADMIN_PHONE = "+254700000001"
DIRECTOR_PHONE = "+254722527234"
ADMIN_EMAIL = "admin@wilkem.test"
DIRECTOR_EMAIL = "director@wilkem.test"


@pytest.fixture
def unmatched_event(db):
    return CoopIpnEvent.objects.create(
        transaction_id="TXN-UNMATCHED-1",
        payment_ref="90290#UNKNOWN",
        amount=Decimal("12000"),
        status=CoopIpnStatus.UNMATCHED,
        detail="No unit matched the payment reference",
        narration="MPESA payment from 0722000000 JOHN DOE",
        raw_payload={},
    )


def _contacts(settings, *, admin_phone="", director_phone="",
              admin_email="", director_email=""):
    settings.ADMIN_ALERT_PHONE = admin_phone
    settings.DIRECTOR_ALERT_PHONE = director_phone
    settings.ADMIN_ALERT_EMAIL = admin_email
    settings.DIRECTOR_ALERT_EMAIL = director_email


@pytest.mark.django_db
def test_alerts_admin_and_director(settings, unmatched_event):
    _contacts(
        settings,
        admin_phone=ADMIN_PHONE, director_phone=DIRECTOR_PHONE,
        admin_email=ADMIN_EMAIL, director_email=DIRECTOR_EMAIL,
    )
    with patch("apps.payments.notifications.send_sms") as sms, \
            patch("apps.payments.notifications.send_email") as email:
        send_unmatched_credit_alert(unmatched_event.id)

    assert {c.args[0] for c in sms.call_args_list} == {ADMIN_PHONE, DIRECTOR_PHONE}
    assert {c.args[0] for c in email.call_args_list} == {ADMIN_EMAIL, DIRECTOR_EMAIL}


@pytest.mark.django_db
def test_director_alone_still_alerted(settings, unmatched_event):
    """Removing the admin contact must not silence the alert."""
    _contacts(settings, director_phone=DIRECTOR_PHONE, director_email=DIRECTOR_EMAIL)
    with patch("apps.payments.notifications.send_sms") as sms, \
            patch("apps.payments.notifications.send_email") as email:
        send_unmatched_credit_alert(unmatched_event.id)

    assert [c.args[0] for c in sms.call_args_list] == [DIRECTOR_PHONE]
    assert [c.args[0] for c in email.call_args_list] == [DIRECTOR_EMAIL]


@pytest.mark.django_db
def test_shared_contact_is_not_messaged_twice(settings, unmatched_event):
    """Same number in both slots costs one SMS, not two."""
    _contacts(settings, admin_phone=DIRECTOR_PHONE, director_phone=DIRECTOR_PHONE)
    with patch("apps.payments.notifications.send_sms") as sms, \
            patch("apps.payments.notifications.send_email"):
        send_unmatched_credit_alert(unmatched_event.id)

    assert sms.call_count == 1


@pytest.mark.django_db
def test_no_contacts_configured_sends_nothing(settings, unmatched_event):
    _contacts(settings)
    with patch("apps.payments.notifications.send_sms") as sms, \
            patch("apps.payments.notifications.send_email") as email:
        send_unmatched_credit_alert(unmatched_event.id)

    sms.assert_not_called()
    email.assert_not_called()


@pytest.mark.django_db
def test_alert_points_at_reconciliation_not_django_admin(settings, unmatched_event):
    """The director works in the dashboard, not /admin/ — the copy must say so."""
    _contacts(settings, director_phone=DIRECTOR_PHONE, director_email=DIRECTOR_EMAIL)
    with patch("apps.payments.notifications.send_sms") as sms, \
            patch("apps.payments.notifications.send_email") as email:
        send_unmatched_credit_alert(unmatched_event.id)

    sms_text = sms.call_args.args[1]
    assert "Reconciliation" in sms_text
    assert "Admin" not in sms_text

    email_html = email.call_args.args[2]  # (recipient, subject, html)
    assert "Reconciliation" in email_html
    assert "Co-op IPN events" not in email_html
