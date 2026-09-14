"""SMS_ENABLED / TENANT_EMAIL_ENABLED are hard stops: with both off, no tenant
receives an SMS or an email by any path, manual sends included."""
from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest

from apps.buildings.models import Building, Unit, UnitStatus
from apps.payments.models import NotificationChannel, TenantNotification
from apps.tenants.models import Tenant, TenantStatus


@pytest.fixture(autouse=True)
def messaging_off(settings):
    settings.SMS_ENABLED = False
    settings.TENANT_EMAIL_ENABLED = False
    settings.TENANT_NOTIFICATIONS_ENABLED = True
    settings.AT_API_KEY = "live-key"
    settings.EMAIL_HOST_USER = "office@example.com"
    settings.EMAIL_HOST_PASSWORD = "secret"


@pytest.fixture
def tenant(db):
    building = Building.objects.create(name="Sunset Apartments", total_floors=2)
    unit = Unit.objects.create(
        building=building, label="B3", monthly_rent=Decimal("12000"),
        status=UnitStatus.OCCUPIED_PAID,
    )
    return Tenant.objects.create(
        first_name="Peter", last_name="Kamau", id_number="98765432",
        phone="+254798765432", email="peter@example.com",
        unit=unit, monthly_rent=Decimal("12000"),
        move_in_date="2026-01-01", status=TenantStatus.ACTIVE,
    )


@patch("apps.payments.notification_services.send_email")
@patch("apps.payments.notification_services.send_sms")
def test_manual_dispatch_on_both_channels_sends_nothing(mock_sms, mock_email, tenant):
    from apps.payments.notification_services import dispatch_notification

    note = TenantNotification.objects.create(
        tenant=tenant, channel=NotificationChannel.BOTH, subject="Notice", body="Hello",
    )
    note = dispatch_notification(note, automatic=False)

    mock_sms.assert_not_called()
    mock_email.assert_not_called()
    assert note.status == "pending"
    assert "Suppressed" in note.error


def test_send_email_refuses_a_tenant_address(tenant, mailoutbox):
    from apps.payments.notifications import send_email

    assert send_email("PETER@example.com", "Statement", "<p>hi</p>") is False
    assert mailoutbox == []


def test_send_email_still_reaches_non_tenant_addresses(db, mailoutbox):
    from apps.payments.notifications import send_email

    assert send_email("director@example.com", "Unmatched credit", "<p>hi</p>") is True
    assert len(mailoutbox) == 1


@patch("apps.payments.notifications.send_email")
def test_manual_statement_email_suppressed(mock_email, tenant):
    from apps.payments.statement_delivery import send_tenant_statement

    note = send_tenant_statement(tenant, automatic=False)

    mock_email.assert_not_called()
    assert note.status == "pending"


@patch("apps.payments.notifications.send_sms")
def test_manual_statement_sms_suppressed(mock_sms, tenant):
    from apps.payments.statement_delivery import send_tenant_statement_sms

    note = send_tenant_statement_sms(tenant, automatic=False)

    mock_sms.assert_not_called()
    assert note.status == "pending"


@patch("httpx.post")
@patch("apps.payments.notifications.send_email")
def test_payment_receipt_sends_nothing(mock_email, mock_post, tenant):
    from apps.payments.tasks import _notify_tenant_payment

    _notify_tenant_payment(tenant, Decimal("12000"), "MPE_TEST_001", date(2026, 4, 13))

    mock_post.assert_not_called()
    mock_email.assert_not_called()
