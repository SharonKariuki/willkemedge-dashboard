"""
Tests for the arrears-reminder SMS job (Day 4 · Feature 6).

Covers the acceptance criteria:
  - auto SMS fires on/after the due day when the current period is unpaid
  - sourced from the canonical Arrears row (matches the tenant statement)
  - does NOT fire before the due day, or when the period is paid/cleared
  - one reminder per tenant per period (idempotent), skips no-phone/non-active
"""
from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest

from apps.buildings.models import Building, Unit, UnitStatus
from apps.payments.models import Arrears, NotificationStatus, TenantNotification
from apps.payments.tasks import send_arrears_reminders
from apps.tenants.models import Tenant, TenantStatus

FIXED_TODAY = date(2026, 6, 15)  # past a due day on the 5th


@pytest.fixture(autouse=True)
def _no_live_sms(settings):
    settings.AT_API_KEY = ""


@pytest.fixture
def building(db):
    return Building.objects.create(name="Road Block", total_floors=4)


def _make_tenant(building, *, due_day=5, phone="+254726012481", id_number="T1",
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


def _arrears(tenant, *, balance="20000", is_cleared=False, month=6, year=2026):
    return Arrears.objects.create(
        tenant=tenant, period_month=month, period_year=year,
        expected_rent=Decimal("20000"), amount_paid=Decimal("20000") - Decimal(balance),
        balance=Decimal(balance), is_cleared=is_cleared,
    )


def _run(today=FIXED_TODAY):
    with patch("apps.payments.tasks.timezone.localdate", return_value=today):
        return send_arrears_reminders()


class TestArrearsReminders:
    def test_fires_when_overdue_and_unpaid_with_message(self, building):
        tenant = _make_tenant(building)
        _arrears(tenant, balance="20000")
        assert _run() == 1
        note = TenantNotification.objects.get(tenant=tenant, template_key="rent_overdue")
        assert note.status == NotificationStatus.SENT
        assert "Sarah Hamisi" in note.body          # tenant name
        assert "20,000" in note.body                 # outstanding balance

    def test_does_not_fire_before_due_day(self, building):
        tenant = _make_tenant(building, due_day=20)  # due 20th, today is the 15th
        _arrears(tenant, balance="20000")
        assert _run() == 0
        assert TenantNotification.objects.count() == 0

    def test_does_not_fire_when_period_cleared(self, building):
        tenant = _make_tenant(building)
        _arrears(tenant, balance="0", is_cleared=True)
        assert _run() == 0

    def test_does_not_fire_without_arrears_row(self, building):
        _make_tenant(building)  # no Arrears row → nothing outstanding
        assert _run() == 0

    def test_idempotent_no_duplicate_on_rerun(self, building):
        tenant = _make_tenant(building)
        _arrears(tenant, balance="20000")
        assert _run() == 1
        assert _run() == 0
        assert TenantNotification.objects.filter(template_key="rent_overdue").count() == 1

    def test_skips_tenant_without_phone(self, building):
        tenant = _make_tenant(building, phone="")
        _arrears(tenant, balance="20000")
        assert _run() == 0

    def test_skips_non_active_tenant(self, building):
        tenant = _make_tenant(building, status=TenantStatus.MOVED_OUT)
        _arrears(tenant, balance="20000")
        assert _run() == 0
