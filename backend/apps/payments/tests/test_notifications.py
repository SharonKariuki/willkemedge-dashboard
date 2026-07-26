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


class TestToIntlPhone:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("0712345678", "+254712345678"),   # local 07…
            ("712345678", "+254712345678"),    # bare subscriber number
            ("254712345678", "+254712345678"), # missing leading +
            ("+254712345678", "+254712345678"),# already E.164
            ("+254 712 345 678", "+254712345678"),  # spaced
            ("0110123456", "+254110123456"),   # newer 01… range
            ("", ""),                          # empty stays empty
        ],
    )
    def test_normalises_kenyan_numbers(self, raw, expected):
        from apps.payments.notifications import to_intl_phone
        assert to_intl_phone(raw) == expected


class TestSendSmsWiring:
    """When a key IS set, the AT payload is well-formed: normalised `to`,
    and a `from` sender ID only when one is configured."""

    @patch("httpx.post")
    @patch("apps.payments.notifications.settings")
    def test_sends_normalised_phone_and_sender_id(self, mock_settings, mock_post):
        mock_settings.AT_API_KEY = "live-key"
        mock_settings.AT_USERNAME = "wilkem"
        mock_settings.AT_SENDER_ID = "WILKEM"
        mock_post.return_value.json.return_value = {"ok": True}

        from apps.payments.notifications import send_sms
        send_sms("0712345678", "Hi")

        _, kwargs = mock_post.call_args
        assert kwargs["data"]["to"] == "+254712345678"
        assert kwargs["data"]["from"] == "WILKEM"
        # Live username → live host, not sandbox.
        assert mock_post.call_args[0][0] == \
            "https://api.africastalking.com/version1/messaging"

    @patch("httpx.post")
    @patch("apps.payments.notifications.settings")
    def test_omits_from_when_no_sender_id(self, mock_settings, mock_post):
        mock_settings.AT_API_KEY = "live-key"
        mock_settings.AT_USERNAME = "wilkem"
        mock_settings.AT_SENDER_ID = ""
        mock_post.return_value.json.return_value = {"ok": True}

        from apps.payments.notifications import send_sms
        send_sms("+254712345678", "Hi")

        _, kwargs = mock_post.call_args
        assert "from" not in kwargs["data"]


class TestAtDeliveryError:
    """A blocked recipient comes back inside an HTTP-200 body — at_delivery_error
    must flag it so the caller records a real failure, not a false 'sent'."""

    def _receipt(self, status, code):
        return {"SMSMessageData": {"Recipients": [{"status": status, "statusCode": code}]}}

    @pytest.mark.parametrize("status,code", [("Success", 101), ("Sent", 100), ("Success", 102)])
    def test_accepted_statuses_return_none(self, status, code):
        from apps.payments.notifications import at_delivery_error
        assert at_delivery_error(self._receipt(status, code)) is None

    def test_blacklist_returns_optout_message(self):
        from apps.payments.notifications import at_delivery_error
        msg = at_delivery_error(self._receipt("UserInBlacklist", 406))
        assert msg is not None
        assert "*456*9#" in msg  # actionable opt-in guidance

    def test_unknown_status_falls_back_to_raw(self):
        from apps.payments.notifications import at_delivery_error
        assert at_delivery_error(self._receipt("SomethingNew", 499)) == "Not delivered (SomethingNew)"

    def test_empty_recipients_is_failure(self):
        from apps.payments.notifications import at_delivery_error
        receipt = {"SMSMessageData": {"Message": "Sent to 0/1", "Recipients": []}}
        assert at_delivery_error(receipt) == "Not delivered: Sent to 0/1"

    def test_none_receipt_is_not_an_error(self):
        # send_sms returns None when no API key is set — that's 'skipped', not failed.
        from apps.payments.notifications import at_delivery_error
        assert at_delivery_error(None) is None


@pytest.mark.django_db
class TestDispatchSurfacesDeliveryFailure:
    """dispatch_notification must not report a carrier-blocked SMS as 'sent'."""

    def _note(self, tenant, channel="sms"):
        from apps.payments.models import NotificationChannel, TenantNotification
        return TenantNotification.objects.create(
            tenant=tenant,
            channel=NotificationChannel.SMS if channel == "sms" else channel,
            subject="",
            body="Test reminder",
        )

    @patch("apps.payments.notification_services.send_sms")
    def test_blacklisted_recipient_marked_failed(self, mock_send, tenant_with_email):
        mock_send.return_value = {
            "SMSMessageData": {
                "Recipients": [
                    {"number": "+254712345678", "status": "UserInBlacklist", "statusCode": 406}
                ]
            }
        }
        from apps.payments.notification_services import dispatch_notification
        note = dispatch_notification(self._note(tenant_with_email))
        assert note.status == "failed"
        assert "*456*9#" in note.error
        # Receipt is still persisted for auditing even though it failed.
        assert "UserInBlacklist" in note.provider_response

    @patch("apps.payments.notification_services.send_sms")
    def test_successful_recipient_marked_sent(self, mock_send, tenant_with_email):
        mock_send.return_value = {
            "SMSMessageData": {
                "Recipients": [
                    {"number": "+254712345678", "status": "Success", "statusCode": 101}
                ]
            }
        }
        from apps.payments.notification_services import dispatch_notification
        note = dispatch_notification(self._note(tenant_with_email))
        assert note.status == "sent"
        assert note.error == ""


class TestSendEmailSkippedWithoutCredentials:
    @patch("apps.payments.notifications.settings")
    def test_logs_warning_when_no_credentials(self, mock_settings, caplog):
        import logging

        mock_settings.EMAIL_HOST_USER = ""
        mock_settings.EMAIL_HOST_PASSWORD = ""
        mock_settings.DEFAULT_FROM_EMAIL = "wilkem.ventures@gmail.com"

        from apps.payments.notifications import send_email
        with caplog.at_level(logging.WARNING):
            send_email("test@example.com", "Subject", "<p>Body</p>")
        assert "EMAIL_HOST_USER/PASSWORD not set" in caplog.text
