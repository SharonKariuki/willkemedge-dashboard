"""
Tests for the per-tenant monthly rent roll (the table behind the tenant page's
"Monthly rent roll"). It mirrors the landlord's spreadsheet, so the figures that
matter are the roll-forward ones: this month's balance is next month's
arrears brought forward.
"""
import datetime as _dt
from decimal import Decimal

import pytest

from apps.buildings.models import Building, Unit, UnitStatus
from apps.payments.models import (
    Arrears,
    Payment,
    PaymentSource,
    PaymentType,
    UtilityCharge,
)
from apps.payments.monthly_ledger import build_monthly_ledger
from apps.tenants.models import Tenant, TenantStatus

TODAY = _dt.date(2026, 8, 24)


@pytest.fixture
def tenant(db):
    building = Building.objects.create(name="Road Block", total_floors=4)
    unit = Unit.objects.create(
        building=building, label="RB999", monthly_rent=Decimal("9000"),
        status=UnitStatus.OCCUPIED_UNPAID,
    )
    return Tenant.objects.create(
        first_name="Stephen", last_name="Oyugi", id_number="TEST-RB999",
        phone="+254700000001", unit=unit, monthly_rent=Decimal("9000"),
        deposit_paid=Decimal("9000"), move_in_date="2026-06-01",
        status=TenantStatus.ACTIVE,
    )


def _bill(tenant, month, rent="9000", paid="0", **kwargs):
    return Arrears.objects.create(
        tenant=tenant, period_month=month, period_year=2026,
        expected_rent=Decimal(rent), amount_paid=Decimal(paid),
        balance=Decimal(rent) - Decimal(paid), **kwargs,
    )


def _pay(tenant, month, amount, ptype=PaymentType.RENT, **kwargs):
    return Payment.objects.create(
        tenant=tenant, amount=Decimal(amount), payment_date=_dt.date(2026, month, 7),
        period_month=month, period_year=2026, source=PaymentSource.MPESA,
        payment_type=ptype, **kwargs,
    )


class TestMonthlyLedger:
    def test_no_records_yields_no_rows(self, tenant):
        assert build_monthly_ledger(tenant, today=TODAY) == []

    def test_balance_rolls_forward_as_next_month_arrears(self, tenant):
        _bill(tenant, 6)
        _pay(tenant, 6, "4000")
        _bill(tenant, 7)
        rows = build_monthly_ledger(tenant, today=_dt.date(2026, 7, 20))

        june, july = rows[0], rows[1]
        assert (june["brought_forward"], june["rent"], june["paid"], june["balance"]) == \
            ("0.00", "9000.00", "4000.00", "5000.00")
        assert july["brought_forward"] == "5000.00"
        assert july["total_due"] == "14000.00"
        assert july["balance"] == "14000.00"

    def test_other_charges_are_added_to_the_month_due(self, tenant):
        _bill(tenant, 6)
        UtilityCharge.objects.create(
            tenant=tenant, posting_date=_dt.date(2026, 6, 30), period_month=6,
            period_year=2026, label="Water Usage", amount=Decimal("450"),
        )
        row = build_monthly_ledger(tenant, today=_dt.date(2026, 6, 30))[0]
        assert row["other_charges"] == "450.00"
        assert row["total_due"] == "9450.00"

    def test_vat_is_part_of_the_obligation(self, tenant):
        _bill(tenant, 6, expected_vat=Decimal("1440"))
        row = build_monthly_ledger(tenant, today=_dt.date(2026, 6, 30))[0]
        assert row["vat"] == "1440.00"
        assert row["total_due"] == "10440.00"

    def test_deposit_and_void_payments_are_not_rent_paid(self, tenant):
        _bill(tenant, 6)
        _pay(tenant, 6, "9000", ptype=PaymentType.DEPOSIT, reference="DEP1")
        _pay(tenant, 6, "9000", reference="VOID1",
             voided_at=_dt.datetime(2026, 6, 8, tzinfo=_dt.UTC))
        row = build_monthly_ledger(tenant, today=_dt.date(2026, 6, 30))[0]
        assert row["paid"] == "0.00"
        assert row["balance"] == "9000.00"

    def test_waiver_discharges_the_balance(self, tenant):
        _bill(tenant, 6, paid="4000", waived_amount=Decimal("5000"))
        _pay(tenant, 6, "4000")
        row = build_monthly_ledger(tenant, today=_dt.date(2026, 6, 30))[0]
        assert row["waived"] == "5000.00"
        assert row["balance"] == "0.00"

    def test_overpayment_carries_as_a_credit(self, tenant):
        _bill(tenant, 6)
        _pay(tenant, 6, "12000")
        rows = build_monthly_ledger(tenant, today=_dt.date(2026, 7, 20))
        assert rows[0]["balance"] == "-3000.00"
        assert rows[1]["brought_forward"] == "-3000.00"

    def test_row_exists_for_the_current_month_before_billing_runs(self, tenant):
        _bill(tenant, 6)
        rows = build_monthly_ledger(tenant, today=TODAY)
        assert [r["period"] for r in rows] == ["6/2026", "7/2026", "8/2026"]
        assert rows[-1]["rent"] == "0.00"
        assert rows[-1]["balance"] == "9000.00"

    def test_months_window_keeps_the_carried_balance_correct(self, tenant):
        _bill(tenant, 6)
        _bill(tenant, 7)
        rows = build_monthly_ledger(tenant, months=1, today=_dt.date(2026, 7, 20))
        assert len(rows) == 1
        assert rows[0]["period"] == "7/2026"
        assert rows[0]["brought_forward"] == "9000.00"


class TestOpeningRow:
    """A carried opening balance is stored as an Arrears row because that is the
    only way to seed the roll-forward. It must not then read as rent: Elimisha's
    July showed "Rent 20,000" against an actual rent of 22,500."""

    def _opening(self, tenant, month, amount):
        return Arrears.objects.create(
            tenant=tenant, period_month=month, period_year=2026,
            expected_rent=Decimal(amount), expected_vat=Decimal("0"),
            amount_paid=Decimal("0"), balance=Decimal(amount),
            waive_notes="Opening position carried from the 21 Aug 2026 statement.",
        )

    def test_opening_reports_as_brought_forward_not_rent(self, tenant):
        self._opening(tenant, 7, "20000")

        row = build_monthly_ledger(tenant, today=_dt.date(2026, 7, 20))[0]

        assert Decimal(row["brought_forward"]) == Decimal("20000.00")
        assert Decimal(row["rent"]) == Decimal("0.00"), "an opening balance read as rent"
        assert row["is_opening"] is True

    def test_the_total_is_unchanged_by_the_move(self, tenant):
        self._opening(tenant, 7, "20000")

        row = build_monthly_ledger(tenant, today=_dt.date(2026, 7, 20))[0]

        assert Decimal(row["total_due"]) == Decimal("20000.00")

    def test_it_still_carries_into_the_next_month(self, tenant):
        """The whole point of the row — moving the figure must not break this."""
        self._opening(tenant, 7, "20000")
        _bill(tenant, 8, rent="22500")

        rows = build_monthly_ledger(tenant, today=_dt.date(2026, 8, 20))
        august = rows[-1]

        assert Decimal(august["brought_forward"]) == Decimal("20000.00")
        assert Decimal(august["total_due"]) == Decimal("42500.00")

    def test_a_normal_month_is_not_flagged(self, tenant):
        _bill(tenant, 7, rent="9000")

        row = build_monthly_ledger(tenant, today=_dt.date(2026, 7, 20))[0]

        assert row["is_opening"] is False
        assert Decimal(row["rent"]) == Decimal("9000.00")
