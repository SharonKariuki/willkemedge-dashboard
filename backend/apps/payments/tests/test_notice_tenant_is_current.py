"""A tenant who has given notice is still the tenant until they move out.

Billing, the reminders, the statement run and the payment matcher used to look
for ACTIVE tenants alone. The day notice was recorded the tenant dropped out of
all of them: their last month's rent was never raised, nobody reminded them,
no statement went, and the rent they paid in with their own unit code landed
in the unmatched queue.

They are billed up to the month they said they would leave, and no further.
"""
import datetime as dt
from decimal import Decimal
from unittest.mock import patch

import pytest

from apps.buildings.models import Building, Unit, UnitClassification, UnitStatus
from apps.payments.billing_calendar import RENT_DUE_DAY
from apps.payments.matching import match_tenant, tenant_by_phone
from apps.payments.models import Arrears, TenantNotification
from apps.payments.tasks import (
    generate_monthly_arrears,
    send_monthly_statements,
    send_rent_reminders,
)
from apps.tenants.models import Tenant, TenantStatus

D = Decimal
RESIDENTIAL_DAY = dt.date(2026, 9, 28)  # houses are invoiced for October


@pytest.fixture(autouse=True)
def _messaging_on(settings):
    settings.EMAIL_HOST_USER = "wilkem.ventures@gmail.com"
    settings.EMAIL_HOST_PASSWORD = "app-password"
    settings.TENANT_NOTIFICATIONS_ENABLED = True
    settings.SMS_ENABLED = True
    settings.TENANT_EMAIL_ENABLED = True


@pytest.fixture
def building(db):
    return Building.objects.create(name="Notice Block", code="NB", total_floors=1)


def _tenant(building, label, *, status=TenantStatus.NOTICE_GIVEN, leaving=None,
            phone="+254711000001"):
    unit = Unit.objects.create(
        building=building, label=label, monthly_rent=D("15000"),
        status=UnitStatus.OCCUPIED_UNPAID, classification=UnitClassification.RESIDENTIAL,
    )
    return Tenant.objects.create(
        first_name="Notice", last_name=label, id_number=f"ID-{label}",
        phone=phone, email=f"{label.lower()}@example.com", unit=unit,
        monthly_rent=D("15000"), due_day=RENT_DUE_DAY, move_in_date="2026-07-01",
        status=status,
        notice_date=dt.date(2026, 9, 1) if status == TenantStatus.NOTICE_GIVEN else None,
        intended_move_out_date=leaving,
    )


def _periods(tenant):
    return set(Arrears.objects.filter(tenant=tenant).values_list("period_year", "period_month"))


def _bill(on):
    with patch("apps.payments.tasks.timezone.localdate", return_value=on):
        return generate_monthly_arrears()


class TestBilling:
    def test_a_tenant_leaving_after_next_month_is_still_billed(self, building):
        tenant = _tenant(building, "NB1", leaving=dt.date(2026, 10, 31))
        _bill(RESIDENTIAL_DAY)
        assert (2026, 10) in _periods(tenant)

    def test_billing_stops_at_the_move_out_month(self, building):
        """Leaving 30 September: September is owed, October is never raised."""
        tenant = _tenant(building, "NB2", leaving=dt.date(2026, 9, 30))
        _bill(RESIDENTIAL_DAY)
        periods = _periods(tenant)
        assert (2026, 9) in periods
        assert (2026, 10) not in periods

    def test_notice_without_a_date_is_billed_like_an_active_tenant(self, building):
        tenant = _tenant(building, "NB3", leaving=None)
        _bill(RESIDENTIAL_DAY)
        assert (2026, 10) in _periods(tenant)

    def test_moved_out_tenants_are_still_not_billed(self, building):
        tenant = _tenant(building, "NB4", status=TenantStatus.MOVED_OUT)
        _bill(RESIDENTIAL_DAY)
        assert _periods(tenant) == set()


class TestPaymentMatching:
    def test_their_unit_code_matches(self, building):
        tenant = _tenant(building, "NB5", leaving=dt.date(2026, 10, 31))
        assert match_tenant("90290#NB5") == tenant

    def test_their_phone_matches(self, building):
        tenant = _tenant(building, "NB6", leaving=dt.date(2026, 10, 31), phone="+254722333444")
        assert tenant_by_phone("254722333444") == tenant


class TestReminders:
    def _remind(self, on):
        with patch("apps.payments.tasks.timezone.localdate", return_value=on), \
                patch("apps.payments.notification_services.send_sms", return_value=True), \
                patch("apps.payments.notifications.send_sms", return_value=True):
            send_rent_reminders()

    def test_reminded_for_a_month_they_still_owe(self, building):
        tenant = _tenant(building, "NB7", leaving=dt.date(2026, 10, 31))
        self._remind(dt.date(2026, 10, 3))
        assert TenantNotification.objects.filter(
            tenant=tenant, template_key="rent_reminder",
        ).exists()

    def test_not_reminded_after_they_have_left(self, building):
        tenant = _tenant(building, "NB8", leaving=dt.date(2026, 9, 30))
        self._remind(dt.date(2026, 10, 3))
        assert not TenantNotification.objects.filter(
            tenant=tenant, template_key="rent_reminder",
        ).exists()


class TestStatements:
    def _state(self, on):
        with patch("apps.payments.tasks.timezone.localdate", return_value=on), \
                patch("apps.payments.notifications.send_email", return_value=True), \
                patch("apps.payments.notifications.send_sms", return_value=True):
            generate_monthly_arrears()
            return send_monthly_statements()

    def test_a_notice_tenant_gets_their_invoice(self, building):
        _tenant(building, "NB9", leaving=dt.date(2026, 10, 31))
        result = self._state(RESIDENTIAL_DAY)
        assert result["periods"].get("2026-10") == 1

    def test_no_invoice_for_a_month_after_they_leave(self, building):
        _tenant(building, "NB10", leaving=dt.date(2026, 9, 30))
        result = self._state(RESIDENTIAL_DAY)
        assert result["past_move_out"] == 1
        assert "2026-10" not in result["periods"]


class TestDashboard:
    def test_a_tenant_leaving_soon_raises_the_move_out_alert(self, building):
        from django.contrib.auth import get_user_model
        from django.utils import timezone
        from rest_framework.test import APIClient

        today = timezone.localdate()
        tenant = _tenant(building, "NB11", leaving=today + dt.timedelta(days=10))
        user = get_user_model().objects.create_user(
            username="dash", email="dash@test.com", password="testpass123!", role="owner",
        )
        client = APIClient()
        client.force_authenticate(user=user)

        data = client.get("/api/dashboard/summary/").json()

        alerts = [a for a in data["alerts"] if a["type"] == "move_out"]
        assert [a["tenant_id"] for a in alerts] == [tenant.id]
        assert "10 days" in alerts[0]["message"]
        assert data["kpis"]["active_tenants"] == 1
