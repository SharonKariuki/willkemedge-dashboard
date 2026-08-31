"""
Tests for removing June 2026 from Road Block Eldoret.

June is the property's opening cutover, so the command deletes real records on
purpose. What is pinned here is the blast radius: June goes, nothing else does,
and cash the tenant actually paid survives even when its period says June.
"""
import datetime as _dt
from decimal import Decimal

import pytest
from django.core.management import call_command

from apps.buildings.models import Building, Unit, UnitClassification, UnitStatus
from apps.ledger.models import JournalEntry
from apps.payments.models import Arrears, Payment
from apps.tenants.models import Tenant, TenantStatus


@pytest.fixture
def road_block(db):
    building = Building.objects.create(
        name="Wilkem Edge Apartments - Road Block Eldoret", address="Eldoret"
    )
    other = Building.objects.create(name="Wilkem Edge Villas - Mt View", address="Nairobi")
    made = {}
    for label, home in (("RB101", building), ("MV101", other)):
        unit = Unit.objects.create(
            building=home, label=label, monthly_rent=Decimal("8300"),
            classification=UnitClassification.RESIDENTIAL, status=UnitStatus.OCCUPIED_UNPAID,
        )
        tenant = Tenant.objects.create(
            unit=unit, first_name=label, last_name="Tenant",
            phone=f"+2547000{label[-3:]}", id_number=f"ID-{label}",
            monthly_rent=Decimal("8300"),
            status=TenantStatus.ACTIVE, due_day=5, move_in_date=_dt.date(2026, 6, 16),
        )
        for month in (6, 7, 8):
            Arrears.objects.create(
                tenant=tenant, period_year=2026, period_month=month,
                expected_rent=Decimal("8300"), amount_paid=Decimal("0"),
                balance=Decimal("8300"), is_cleared=False,
            )
        for month in (6, 7):
            JournalEntry.objects.create(
                building=home, date=_dt.date(2026, month, 16), period_year=2026,
                period_month=month, memo=f"Opening security deposit held - {label}",
            )
        made[label] = tenant
    return building, made


def _periods(tenant):
    return sorted(
        Arrears.objects.filter(tenant=tenant).values_list("period_month", flat=True)
    )


class TestDryRun:
    def test_dry_run_deletes_nothing(self, road_block):
        _, made = road_block
        call_command("remove_june_road_block")
        assert _periods(made["RB101"]) == [6, 7, 8]
        assert JournalEntry.objects.filter(period_month=6).count() == 2


class TestApply:
    def test_june_arrears_are_gone(self, road_block):
        _, made = road_block
        call_command("remove_june_road_block", "--apply")
        assert _periods(made["RB101"]) == [7, 8]

    def test_june_journal_entries_are_gone(self, road_block):
        building, _ = road_block
        call_command("remove_june_road_block", "--apply")
        assert not JournalEntry.objects.filter(
            building=building, period_year=2026, period_month=6
        ).exists()

    def test_july_and_august_survive(self, road_block):
        building, _ = road_block
        call_command("remove_june_road_block", "--apply")
        assert JournalEntry.objects.filter(building=building, period_month=7).exists()
        assert Arrears.objects.filter(
            tenant__unit__building=building, period_month=8
        ).exists()

    def test_other_properties_are_untouched(self, road_block):
        _, made = road_block
        call_command("remove_june_road_block", "--apply")
        assert _periods(made["MV101"]) == [6, 7, 8]
        assert JournalEntry.objects.filter(
            building__name__icontains="Mt View", period_month=6
        ).exists()

    def test_cash_paid_in_june_is_kept(self, road_block):
        _, made = road_block
        tenant = made["RB101"]
        Payment.objects.create(
            tenant=tenant, amount=Decimal("4500"), payment_date=_dt.date(2026, 8, 10),
            period_year=2026, period_month=6, reference="CB0392781_10082026_2",
        )
        call_command("remove_june_road_block", "--apply")
        assert Payment.objects.filter(tenant=tenant, period_month=6).count() == 1

    def test_running_twice_is_safe(self, road_block):
        _, made = road_block
        call_command("remove_june_road_block", "--apply")
        call_command("remove_june_road_block", "--apply")
        assert _periods(made["RB101"]) == [7, 8]
