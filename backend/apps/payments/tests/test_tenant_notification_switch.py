"""Tests for TENANT_NOTIFICATIONS_ENABLED — the tenant-facing master switch.

Two choke points carry every message a tenant can receive:
  * dispatch_notification()  — rent reminders, arrears reminders, broadcasts
  * _notify_tenant_payment() — payment and deposit receipts

Internal admin/director alerts must keep working while the switch is off, so
the figures can be verified without tenants hearing anything.
"""
from decimal import Decimal
from unittest.mock import patch

import pytest

from apps.buildings.models import Building, Unit, UnitStatus
from apps.payments.models import (
    CoopIpnEvent,
    CoopIpnStatus,
    NotificationChannel,
    NotificationStatus,
    TenantNotification,
)
from apps.payments.notification_services import dispatch_notification
from apps.payments.tasks import _notify_tenant_payment, send_unmatched_credit_alert
from apps.tenants.models import Tenant, TenantStatus


@pytest.fixture(autouse=True)
def _no_live_sms(settings):
    # No AT key → send_sms is a no-op returning None (no network in tests).
    settings.AT_API_KEY = ""


@pytest.fixture
def tenant(db):
    building = Building.objects.create(name="Road Block", total_floors=4)
    unit = Unit.objects.create(
        building=building, label="RB-1", monthly_rent=Decimal("20000"),
        status=UnitStatus.OCCUPIED_UNPAID,
    )
    return Tenant.objects.create(
        first_name="Sarah", last_name="Hamisi", id_number="T-SWITCH-1",
        phone="+254726012481", unit=unit, monthly_rent=Decimal("20000"),
        move_in_date="2026-01-01", due_day=5, status=TenantStatus.ACTIVE,
    )


@pytest.fixture
def notification(tenant):
    return TenantNotification.objects.create(
        tenant=tenant,
        channel=NotificationChannel.SMS,
        subject="Rent reminder",
        body="Your rent is due.",
        status=NotificationStatus.PENDING,
    )


# ── dispatch_notification: reminders + admin broadcast ─────────────────────

@pytest.mark.django_db
def test_reminder_suppressed_when_disabled(settings, notification):
    settings.TENANT_NOTIFICATIONS_ENABLED = False
    with patch("apps.payments.notification_services.send_sms") as sms:
        result = dispatch_notification(notification)

    sms.assert_not_called()
    assert result.status == NotificationStatus.PENDING
    assert "Suppressed" in result.error


@pytest.mark.django_db
def test_suppressed_reminder_never_looks_delivered(settings, notification):
    """A suppressed row must not read as SENT — the message is still owed."""
    settings.TENANT_NOTIFICATIONS_ENABLED = False
    with patch("apps.payments.notification_services.send_sms"):
        dispatch_notification(notification)

    notification.refresh_from_db()
    assert notification.status != NotificationStatus.SENT
    assert notification.sent_at is None


@pytest.mark.django_db
def test_reminder_sends_when_enabled(settings, notification):
    settings.TENANT_NOTIFICATIONS_ENABLED = True
    with patch("apps.payments.notification_services.send_sms", return_value=None) as sms:
        dispatch_notification(notification)

    sms.assert_called_once()


# ── _notify_tenant_payment: receipts ───────────────────────────────────────

@pytest.mark.django_db
def test_receipt_suppressed_when_disabled(settings, tenant):
    settings.TENANT_NOTIFICATIONS_ENABLED = False
    with patch("apps.payments.notifications.send_sms") as sms, \
            patch("apps.payments.notifications.send_email") as email:
        _notify_tenant_payment(tenant, Decimal("5000"), "TXN-1", None)

    sms.assert_not_called()
    email.assert_not_called()


# ── internal alerts are deliberately not gated ─────────────────────────────

@pytest.mark.django_db
def test_admin_alerts_still_fire_when_tenant_notifications_disabled(settings):
    """The point of the switch: staff keep their visibility while tenants are quiet."""
    settings.TENANT_NOTIFICATIONS_ENABLED = False
    settings.ADMIN_ALERT_PHONE = "+254700000001"
    settings.ADMIN_ALERT_EMAIL = ""
    settings.DIRECTOR_ALERT_PHONE = ""
    settings.DIRECTOR_ALERT_EMAIL = ""

    event = CoopIpnEvent.objects.create(
        transaction_id="TXN-SWITCH-1",
        amount=Decimal("9000"),
        status=CoopIpnStatus.UNMATCHED,
        detail="No unit matched",
        raw_payload={},
    )
    with patch("apps.payments.notifications.send_sms") as sms:
        send_unmatched_credit_alert(event.id)

    sms.assert_called_once()
