"""
Tests for the rent-reminder SMS job (Day 4 · Feature 5).

Covers the acceptance criteria:
  - fires N days before each tenant's due day (configurable lead window)
  - message includes tenant name, amount due, and due date
  - no duplicate sends on re-schedule (idempotent per tenant per period)
  - skips tenants with no phone / not active
  - Africa's Talking delivery receipt is logged on the notification
"""
from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest

from apps.buildings.models import Building, Unit, UnitStatus
from apps.payments.models import NotificationStatus, TenantNotification
from apps.payments.tasks import send_rent_reminders
from apps.tenants.models import Tenant, TenantStatus

# Mid-month so a ±lead-day window never crosses a month boundary.
FIXED_TODAY = date(2026, 6, 15)


@pytest.fixture(autouse=True)
def _no_live_sms(settings):
    # No AT key → send_sms is a no-op that returns None (no network in tests).
    settings.AT_API_KEY = ""
    settings.RENT_REMINDER_LEAD_DAYS = 3


@pytest.fixture
def building(db):
    return Building.objects.create(name="Road Block", total_floors=4)


def _make_tenant(building, due_day, *, phone="+254726012481", id_number="T1",
                 status=TenantStatus.ACTIVE):
    unit = Unit.objects.create(
        building=building, label=f"RB-{id_number}", monthly_rent=Decimal("20000"),
        status=UnitStatus.OCCUPIED_UNPAID,
    )
    return Tenant.objects.create(
        first_name="Sarah", last_name="Hamisi", id_number=id_number, phone=phone,
        unit=unit, monthly_rent=Decimal("20000"), move_in_date="2026-01-01",
        due_day=due_day, status=status,
    )


def _run(today=FIXED_TODAY):
    with patch("apps.payments.tasks.timezone.localdate", return_value=today):
        return send_rent_reminders()


class TestRentReminders:
    def test_fires_within_lead_window_with_message_content(self, building):
        tenant = _make_tenant(building, due_day=18)  # 3 days from FIXED_TODAY
        assert _run() == 1
        note = TenantNotification.objects.get(tenant=tenant, template_key="rent_reminder")
        assert note.status == NotificationStatus.SENT
        assert "Sarah Hamisi" in note.body   # tenant name
        assert "20,000" in note.body          # amount due
        assert "18" in note.body              # due date (day)

    def test_does_not_fire_outside_window(self, building):
        _make_tenant(building, due_day=28)  # 13 days away
        assert _run() == 0
        assert TenantNotification.objects.count() == 0

    def test_does_not_fire_after_due_date(self, building):
        _make_tenant(building, due_day=10)  # 5 days past
        assert _run() == 0
        assert TenantNotification.objects.count() == 0

    def test_lead_days_is_configurable(self, building, settings):
        settings.RENT_REMINDER_LEAD_DAYS = 7
        _make_tenant(building, due_day=21)  # 6 days out — inside a 7-day window
        assert _run() == 1

    def test_idempotent_no_duplicate_on_rerun(self, building):
        _make_tenant(building, due_day=18)
        assert _run() == 1
        assert _run() == 0  # second run dedupes on the per-period key
        assert TenantNotification.objects.filter(template_key="rent_reminder").count() == 1

    def test_skips_tenant_without_phone(self, building):
        _make_tenant(building, due_day=18, phone="")
        assert _run() == 0
        assert TenantNotification.objects.count() == 0

    def test_skips_non_active_tenant(self, building):
        _make_tenant(building, due_day=18, status=TenantStatus.MOVED_OUT)
        assert _run() == 0

    def test_clamps_due_day_to_short_month(self, building):
        # due_day 31 in June (30 days) clamps to the 30th; from the 15th that's
        # 15 days out — outside the 3-day window, so it must NOT fire (and must
        # not raise on the invalid date(2026, 6, 31)).
        _make_tenant(building, due_day=31)
        assert _run() == 0

    @patch("apps.payments.notification_services.send_sms")
    def test_delivery_receipt_persisted(self, mock_send, building):
        mock_send.return_value = {
            "SMSMessageData": {
                "Recipients": [
                    {"messageId": "ATXid_test123", "status": "Success", "cost": "KES 0.8000"}
                ]
            }
        }
        _make_tenant(building, due_day=18)
        assert _run() == 1
        note = TenantNotification.objects.get(template_key="rent_reminder")
        assert note.provider_message_id == "ATXid_test123"
        assert "ATXid_test123" in note.provider_response
