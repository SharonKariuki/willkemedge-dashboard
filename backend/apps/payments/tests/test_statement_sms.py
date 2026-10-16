"""
Texting tenants their statement summary.

Covers:
  - the SMS carries the statement summary and records the provider receipt
  - no phone, an unconfigured account, a carrier refusal and a provider error
    are all recorded as FAILED with the reason, never as a silent success
  - the master switch and STATEMENT_SMS_ENABLED silence the automatic send only
  - the monthly run texts tenants with no email, dedupes on its own key, and
    retries a failed SMS even when that month's email already went
"""
from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest

from apps.buildings.models import Building, Unit, UnitStatus
from apps.payments.models import NotificationChannel, NotificationStatus, TenantNotification
from apps.payments.statement_delivery import send_tenant_statement_sms
from apps.payments.tasks import send_monthly_statements
from apps.tenants.models import Tenant, TenantStatus

AS_AT = date(2026, 9, 2)

AT_OK = {"SMSMessageData": {"Recipients": [
    {"status": "Success", "statusCode": 101, "messageId": "ATXid_statement_1"},
]}}
AT_BLACKLISTED = {"SMSMessageData": {"Recipients": [
    {"status": "UserInBlacklist", "statusCode": 406},
]}}


@pytest.fixture(autouse=True)
def _channels_on(settings):
    settings.EMAIL_HOST_USER = "wilkem.ventures@gmail.com"
    settings.EMAIL_HOST_PASSWORD = "app-password"
    settings.TENANT_NOTIFICATIONS_ENABLED = True
    settings.STATEMENT_SMS_ENABLED = True
    # Any send a test forgets to patch returns "not configured" instead of
    # reaching Africa's Talking.
    settings.AT_API_KEY = ""


@pytest.fixture
def building(db):
    return Building.objects.create(name="Road Block", total_floors=4)


def _make_tenant(building, *, email="tenant@example.com", phone="+254726012481", id_number="T1"):
    unit = Unit.objects.create(
        building=building, label=f"RB-{id_number}", monthly_rent=Decimal("20000"),
        status=UnitStatus.OCCUPIED_UNPAID,
    )
    return Tenant.objects.create(
        first_name="Sarah", last_name="Hamisi", id_number=id_number,
        phone=phone, email=email, unit=unit,
        monthly_rent=Decimal("20000"), move_in_date="2026-01-01", status=TenantStatus.ACTIVE,
    )


class TestSendTenantStatementSms:
    def test_sends_the_summary_and_records_the_receipt(self, building):
        tenant = _make_tenant(building)
        with patch("apps.payments.notifications.send_sms", return_value=AT_OK) as send:
            note = send_tenant_statement_sms(tenant, statement_date=AS_AT)

        assert note.status == NotificationStatus.SENT
        assert note.channel == NotificationChannel.SMS
        assert note.template_key == "rent_statement_sms"
        assert note.sent_at is not None
        assert note.provider_message_id == "ATXid_statement_1"
        phone, body = send.call_args.args
        assert phone == "+254726012481"
        assert body == note.body
        assert "Unpaid Balance" in body and "Wilkem Edge" in body

    def test_no_phone_fails_with_the_reason(self, building):
        tenant = _make_tenant(building, phone="")
        with patch("apps.payments.notifications.send_sms") as send:
            note = send_tenant_statement_sms(tenant, statement_date=AS_AT)

        send.assert_not_called()
        assert note.status == NotificationStatus.FAILED
        assert "no phone number" in note.error

    def test_an_unconfigured_account_is_a_failure_not_a_silent_success(self, building):
        tenant = _make_tenant(building)

        note = send_tenant_statement_sms(tenant, statement_date=AS_AT)

        assert note.status == NotificationStatus.FAILED
        assert "AT_API_KEY" in note.error

    def test_a_carrier_refusal_is_recorded_as_failed(self, building):
        """Africa's Talking answers 200 for a blacklisted number."""
        tenant = _make_tenant(building)
        with patch("apps.payments.notifications.send_sms", return_value=AT_BLACKLISTED):
            note = send_tenant_statement_sms(tenant, statement_date=AS_AT)

        assert note.status == NotificationStatus.FAILED
        assert note.error

    def test_a_provider_error_is_recorded_and_does_not_raise(self, building):
        tenant = _make_tenant(building)
        with patch("apps.payments.notifications.send_sms", side_effect=OSError("timeout")):
            note = send_tenant_statement_sms(tenant, statement_date=AS_AT)

        assert note.status == NotificationStatus.FAILED
        assert "timeout" in note.error

    def test_the_master_switch_silences_the_automatic_send_only(self, building, settings):
        settings.TENANT_NOTIFICATIONS_ENABLED = False
        tenant = _make_tenant(building)
        with patch("apps.payments.notifications.send_sms", return_value=AT_OK) as send:
            automatic = send_tenant_statement_sms(tenant, statement_date=AS_AT)
            assert automatic.status == NotificationStatus.PENDING
            send.assert_not_called()

            manual = send_tenant_statement_sms(tenant, statement_date=AS_AT, automatic=False)
            assert manual.status == NotificationStatus.SENT

    def test_statement_sms_can_be_switched_off_on_its_own(self, building, settings):
        settings.STATEMENT_SMS_ENABLED = False
        tenant = _make_tenant(building)
        with patch("apps.payments.notifications.send_sms") as send:
            note = send_tenant_statement_sms(tenant, statement_date=AS_AT)

        send.assert_not_called()
        assert note.status == NotificationStatus.PENDING
        assert "statement SMS is disabled" in note.error


class TestMonthlyRunTextsTenants:
    def test_a_tenant_with_no_email_still_gets_the_sms(self, building):
        """Most of the roster has no email on file; for them the SMS is the only copy."""
        _make_tenant(building, email="")

        with patch("apps.payments.notifications.send_email", return_value=True) as email, \
             patch("apps.payments.notifications.send_sms", return_value=AT_OK):
            counts = send_monthly_statements(AS_AT.isoformat())

        email.assert_not_called()
        assert counts["no_email"] == 1
        assert counts["sms_sent"] == 1
        assert TenantNotification.objects.filter(channel=NotificationChannel.SMS).count() == 1

    def test_a_tenant_with_no_phone_is_counted(self, building):
        _make_tenant(building, phone="")

        with patch("apps.payments.notifications.send_email", return_value=True), \
             patch("apps.payments.notifications.send_sms") as sms:
            counts = send_monthly_statements(AS_AT.isoformat())

        sms.assert_not_called()
        assert counts["sent"] == 1
        assert counts["no_phone"] == 1

    def test_rerunning_the_same_month_does_not_text_twice(self, building):
        _make_tenant(building)

        with patch("apps.payments.notifications.send_email", return_value=True), \
             patch("apps.payments.notifications.send_sms", return_value=AT_OK) as sms:
            first = send_monthly_statements(AS_AT.isoformat())
            second = send_monthly_statements(AS_AT.isoformat())

        assert first["sms_sent"] == 1
        assert second["sms_skipped"] == 1 and second["sms_sent"] == 0
        assert sms.call_count == 1

    def test_a_failed_sms_is_retried_even_though_the_email_went(self, building):
        _make_tenant(building)

        with patch("apps.payments.notifications.send_email", return_value=True), \
             patch("apps.payments.notifications.send_sms", side_effect=OSError("timeout")):
            first = send_monthly_statements(AS_AT.isoformat())
        with patch("apps.payments.notifications.send_email", return_value=True) as email, \
             patch("apps.payments.notifications.send_sms", return_value=AT_OK):
            second = send_monthly_statements(AS_AT.isoformat())

        assert (first["sent"], first["sms_failed"]) == (1, 1)
        assert (second["skipped"], second["sms_sent"]) == (1, 1)
        email.assert_not_called()
