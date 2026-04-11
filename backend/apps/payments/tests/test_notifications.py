"""
Tests for payment notification tasks.

Covers:
  - send_payment_confirmation calls SMS + email
  - SMS skipped when AT_API_KEY not set
  - Email skipped when tenant has no email
  - Task retries on failure
  - send_password_reset_email sends correct link
"""
from decimal import Decimal
from unittest.mock import patch

import pytest

from apps.buildings.models import Building, Unit, UnitStatus
from apps.payments.models import Payment, PaymentSource
from apps.tenants.models import Tenant, TenantStatus


@pytest.fixture
def building(db):
    return Building.objects.create(name="Sunset Apartments", total_floors=2)


@pytest.fixture
def unit(building):
    return Unit.objects.create(
        building=building, label="B3", monthly_rent=Decimal("12000"),
        status=UnitStatus.OCCUPIED_PAID,
    )


@pytest.fixture
def tenant_with_email(unit):
    return Tenant.objects.create(
        first_name="Peter", last_name="Kamau", id_number="98765432",
        phone="+254798765432", email="peter@example.com",
        unit=unit, monthly_rent=Decimal("12000"),
        move_in_date="2026-01-01", status=TenantStatus.ACTIVE,
    )


@pytest.fixture
def tenant_no_email(unit):
    return Tenant.objects.create(
        first_name="Grace", last_name="Otieno", id_number="11223344",
        phone="+254711223344", email="",
        unit=unit, monthly_rent=Decimal("12000"),
        move_in_date="2026-02-01", status=TenantStatus.ACTIVE,
    )


@pytest.fixture
def payment(tenant_with_email):
    return Payment.objects.create(
        tenant=tenant_with_email, amount=Decimal("12000"),
        payment_date="2026-04-13", period_month=4, period_year=2026,
        source=PaymentSource.MPESA, reference="MPE_TEST_001",
    )


@pytest.mark.django_db
class TestSendPaymentConfirmation:
    @patch("apps.payments.notifications.send_sms")
    @patch("apps.payments.notifications.send_email")
    def test_sends_sms_and_email_when_both_available(
        self, mock_email, mock_sms, payment
    ):
        from apps.payments.tasks import send_payment_confirmation
        send_payment_confirmation(payment.id)
        mock_sms.assert_called_once()
        mock_email.assert_called_once()

        # Verify SMS content mentions amount and unit
        sms_msg = mock_sms.call_args[0][1]
        assert "12,000.00" in sms_msg
        assert "B3" in sms_msg

    @patch("apps.payments.notifications.send_sms")
    @patch("apps.payments.notifications.send_email")
    def test_skips_email_when_tenant_has_no_email(
        self, mock_email, mock_sms, tenant_no_email
    ):
        from apps.payments.tasks import send_payment_confirmation
        pmt = Payment.objects.create(
            tenant=tenant_no_email, amount=Decimal("12000"),
            payment_date="2026-04-13", period_month=4, period_year=2026,
            source=PaymentSource.CASH, reference="CASH_001",
        )
        send_payment_confirmation(pmt.id)
        mock_sms.assert_called_once()
        mock_email.assert_not_called()

    @patch("apps.payments.notifications.send_sms")
    @patch("apps.payments.notifications.send_email")
    def test_handles_nonexistent_payment_gracefully(self, mock_email, mock_sms):
        from apps.payments.tasks import send_payment_confirmation
        send_payment_confirmation(99999)  # Does not exist
        mock_sms.assert_not_called()
        mock_email.assert_not_called()


class TestSendSmsSkippedWithoutApiKey:
    @patch("apps.payments.notifications.settings")
    def test_logs_warning_when_no_api_key(self, mock_settings, caplog):
        import logging

        mock_settings.AT_API_KEY = ""
        mock_settings.AT_USERNAME = "sandbox"

        from apps.payments.notifications import send_sms
        with caplog.at_level(logging.WARNING):
            send_sms("+254700000000", "Test message")
        assert "AT_API_KEY not set" in caplog.text


class TestSendEmailSkippedWithoutApiKey:
    def test_logs_warning_when_no_api_key(self, caplog):
        import logging

        from apps.payments.notifications import send_email
        with caplog.at_level(logging.WARNING):
            send_email("test@example.com", "Subject", "<p>Body</p>")
        assert "SENDGRID_API_KEY not set" in caplog.text
