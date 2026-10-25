"""Quarterly billing — a letting invoiced a calendar quarter in advance.

Ignite (MCG07) is billed Oct–Dec together on the October invoice, raised on
25 September: 3 x 69,600 = 208,800, as the 7 Oct 2026 statement reads. The
books still hold one Arrears row per month, so what has to hold is:

  * the run raises to the end of the quarter, and the next two runs find
    nothing new;
  * the statement carries the whole quarter from the day it was invoiced, and
    states it as one block in the summary box;
  * a monthly letting is untouched.
"""
import datetime as dt
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.core.management import call_command

from apps.buildings.models import Building, Unit, UnitClassification, UnitStatus
from apps.payments.billing_calendar import billed_from, billed_through, quarter_bounds
from apps.payments.models import Arrears
from apps.payments.statement_service import build_statement
from apps.payments.tasks import generate_monthly_arrears
from apps.tenants.models import BillingFrequency, Tenant, TenantStatus

D = Decimal


@pytest.fixture
def building(db):
    return Building.objects.create(name="Matasia Arcade", code="MCR", total_floors=2)


def _tenant(building, label, frequency=BillingFrequency.MONTHLY):
    unit = Unit.objects.create(
        building=building, label=label, monthly_rent=D("60000"),
        classification=UnitClassification.BUSINESS, status=UnitStatus.OCCUPIED_UNPAID,
    )
    return Tenant.objects.create(
        first_name="Ignite", last_name=label, id_number=f"ID-{label}",
        phone="+254727070946", unit=unit, monthly_rent=D("60000"),
        move_in_date="2026-09-01", status=TenantStatus.ACTIVE,
        billing_frequency=frequency,
    )


def _periods(tenant):
    return sorted(Arrears.objects.filter(tenant=tenant).values_list("period_year", "period_month"))


def _run(on):
    with patch("apps.payments.tasks.timezone.localdate", return_value=on):
        generate_monthly_arrears()


class TestCalendar:
    @pytest.mark.parametrize("month,first,last", [(1, 1, 3), (5, 4, 6), (9, 7, 9), (12, 10, 12)])
    def test_quarter_bounds(self, month, first, last):
        assert quarter_bounds((2026, month)) == ((2026, first), (2026, last))

    def test_a_quarterly_month_is_billed_from_its_quarter(self, building):
        tenant = _tenant(building, "MCG07", BillingFrequency.QUARTERLY)
        assert billed_from(tenant, (2026, 11)) == (2026, 10)

    def test_a_monthly_month_is_billed_from_itself(self, building):
        tenant = _tenant(building, "MCG01")
        assert billed_from(tenant, (2026, 11)) == (2026, 11)
        assert billed_through(tenant, dt.date(2026, 9, 25)) == (2026, 10)


class TestTheRun:
    def test_the_25th_before_a_quarter_raises_the_whole_quarter(self, building):
        tenant = _tenant(building, "MCG07", BillingFrequency.QUARTERLY)
        _run(dt.date(2026, 9, 25))
        assert _periods(tenant) == [(2026, 9), (2026, 10), (2026, 11), (2026, 12)]

    def test_runs_inside_the_quarter_raise_nothing_new(self, building):
        tenant = _tenant(building, "MCG07", BillingFrequency.QUARTERLY)
        _run(dt.date(2026, 9, 25))
        _run(dt.date(2026, 10, 25))
        _run(dt.date(2026, 11, 25))
        assert _periods(tenant)[-1] == (2026, 12)
        _run(dt.date(2026, 12, 25))
        assert _periods(tenant)[-1] == (2027, 3)

    def test_a_monthly_letting_is_raised_one_month_ahead(self, building):
        tenant = _tenant(building, "MCG01")
        _run(dt.date(2026, 9, 25))
        assert _periods(tenant) == [(2026, 9), (2026, 10)]


class TestTheStatement:
    def test_the_quarter_is_stated_as_one_block(self, building):
        tenant = _tenant(building, "MCG07", BillingFrequency.QUARTERLY)
        _run(dt.date(2026, 9, 25))
        Arrears.objects.filter(tenant=tenant, period_month=9).delete()

        s = build_statement(tenant, statement_date=dt.date(2026, 10, 7), as_of=dt.date(2026, 10, 7))

        assert s["current_month_charged"] == "208,800.00"
        assert s["vat_on_rent"] == "28,800.00"
        assert s["total_due_value"] == D("208800.00")
        assert s["current_period_label"].startswith("October")
        assert s["current_period_label"].endswith("December-2026")

    def test_a_cut_before_the_invoice_carries_none_of_the_quarter(self, building):
        tenant = _tenant(building, "MCG07", BillingFrequency.QUARTERLY)
        _run(dt.date(2026, 9, 25))
        Arrears.objects.filter(tenant=tenant, period_month=9).delete()

        s = build_statement(tenant, statement_date=dt.date(2026, 9, 30), as_of=dt.date(2026, 9, 30))

        assert s["total_due_value"] == D("0.00")


class TestTheCommand:
    def test_switching_to_quarterly_raises_the_rest_of_the_quarter(self, building):
        tenant = _tenant(building, "MCG07")
        _run(dt.date(2026, 9, 25))
        with patch("apps.payments.tasks.timezone.localdate", return_value=dt.date(2026, 10, 7)), \
             patch("apps.payments.billing_calendar.timezone.localdate", return_value=dt.date(2026, 10, 7)):
            call_command("set_billing_frequency", "MCG07", "quarterly", "--apply")

        tenant.refresh_from_db()
        assert tenant.billing_frequency == BillingFrequency.QUARTERLY
        assert _periods(tenant) == [(2026, 9), (2026, 10), (2026, 11), (2026, 12)]

    def test_dry_run_writes_nothing(self, building):
        tenant = _tenant(building, "MCG07")
        _run(dt.date(2026, 9, 25))
        call_command("set_billing_frequency", "MCG07", "quarterly")

        tenant.refresh_from_db()
        assert tenant.billing_frequency == BillingFrequency.MONTHLY
        assert _periods(tenant) == [(2026, 9), (2026, 10)]
