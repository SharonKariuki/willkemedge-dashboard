"""
A unit's status must describe what the tenant owes, not only how the current
month is going.

MCG10 read "Paid" on the units board while carrying 43,800 forward, because the
rule only ever looked at the current period. These tests pin the fix and the
ARREARS status it finally assigns — a status that had a badge, a filter and a
dashboard count, but which nothing outside seed data had ever set.
"""
import datetime as _dt
from decimal import Decimal

import pytest

from apps.buildings.models import Building, Unit, UnitClassification, UnitStatus
from apps.buildings.services import has_unsettled_earlier_months, recalculate_unit_status
from apps.payments.models import Arrears
from apps.tenants.models import Tenant, TenantStatus

D = Decimal
TODAY = _dt.date(2026, 8, 28)


@pytest.fixture
def let_unit(db):
    building = Building.objects.create(name="Matasia Arcade", code="MCS", total_floors=2)
    unit = Unit.objects.create(
        building=building, label="MCS10", monthly_rent=D("25000"),
        classification=UnitClassification.BUSINESS, status=UnitStatus.OCCUPIED_UNPAID,
    )
    tenant = Tenant.objects.create(
        first_name="Shamiri", last_name="Ltd", id_number="S-MCS10",
        phone="+254700000005", unit=unit, monthly_rent=D("25000"),
        deposit_paid=D("75000"), move_in_date="2026-07-01", status=TenantStatus.ACTIVE,
    )
    return unit, tenant


def _owing(tenant, month, amount):
    return Arrears.objects.create(
        tenant=tenant, period_month=month, period_year=2026,
        expected_rent=D(amount), expected_vat=D("0"),
        amount_paid=D("0"), balance=D(amount), is_cleared=False,
    )


def _settled(tenant, month, amount):
    return Arrears.objects.create(
        tenant=tenant, period_month=month, period_year=2026,
        expected_rent=D(amount), expected_vat=D("0"),
        amount_paid=D(amount), balance=D("0"), is_cleared=True,
    )


class TestPriorArrearsDetection:
    def test_an_unsettled_earlier_month_is_found(self, let_unit, monkeypatch):
        unit, tenant = let_unit
        _owing(tenant, 7, "43800")
        monkeypatch.setattr("django.utils.timezone.localdate", lambda: TODAY)

        assert has_unsettled_earlier_months(unit) is True

    def test_a_settled_earlier_month_is_not(self, let_unit, monkeypatch):
        unit, tenant = let_unit
        _settled(tenant, 7, "43800")
        monkeypatch.setattr("django.utils.timezone.localdate", lambda: TODAY)

        assert has_unsettled_earlier_months(unit) is False

    def test_the_current_month_does_not_count_as_prior(self, let_unit, monkeypatch):
        """Owing this month is 'unpaid', not 'in arrears' — the distinction is
        the whole point of the badge."""
        unit, tenant = let_unit
        _owing(tenant, 8, "29000")
        monkeypatch.setattr("django.utils.timezone.localdate", lambda: TODAY)

        assert has_unsettled_earlier_months(unit) is False

    def test_a_unit_with_no_live_tenancy_is_not_in_arrears(self, let_unit, monkeypatch):
        unit, tenant = let_unit
        _owing(tenant, 7, "43800")
        tenant.status = TenantStatus.MOVED_OUT
        tenant.save(update_fields=["status"])
        monkeypatch.setattr("django.utils.timezone.localdate", lambda: TODAY)

        assert has_unsettled_earlier_months(unit) is False


class TestStatusRule:
    def test_carried_debt_beats_a_fully_paid_month(self, let_unit, monkeypatch):
        """The MCG10 case: paid this month in full, still owes the last one."""
        unit, tenant = let_unit
        _owing(tenant, 7, "43800")
        monkeypatch.setattr("django.utils.timezone.localdate", lambda: TODAY)

        recalculate_unit_status(unit, D("45000"), obligation=D("41340"))

        unit.refresh_from_db()
        assert unit.status == UnitStatus.ARREARS

    def test_a_clean_tenant_paying_in_full_is_paid(self, let_unit, monkeypatch):
        unit, tenant = let_unit
        _settled(tenant, 7, "25000")
        monkeypatch.setattr("django.utils.timezone.localdate", lambda: TODAY)

        recalculate_unit_status(unit, D("29000"), obligation=D("29000"))

        unit.refresh_from_db()
        assert unit.status == UnitStatus.OCCUPIED_PAID

    def test_a_clean_tenant_paying_part_is_partial(self, let_unit, monkeypatch):
        unit, tenant = let_unit
        monkeypatch.setattr("django.utils.timezone.localdate", lambda: TODAY)

        recalculate_unit_status(unit, D("10000"), obligation=D("29000"))

        unit.refresh_from_db()
        assert unit.status == UnitStatus.OCCUPIED_PARTIAL

    def test_a_vacant_unit_is_left_alone(self, let_unit, monkeypatch):
        unit, tenant = let_unit
        unit.status = UnitStatus.VACANT
        unit.save(update_fields=["status"])
        _owing(tenant, 7, "43800")
        monkeypatch.setattr("django.utils.timezone.localdate", lambda: TODAY)

        recalculate_unit_status(unit, D("0"))

        unit.refresh_from_db()
        assert unit.status == UnitStatus.VACANT
