"""
Tests for the Matasia Commercial statement cleanup.

The acceptance test is the last one: after the command runs, the monthly rent
roll for MCG01 must reproduce the landlord's statement row exactly —
12,000 b/f + 24,000 rent + 3,840 VAT = 39,840 due, 27,840 paid, 12,000 owing.
Everything above it exists to pin the pieces that get there.
"""
import datetime as _dt
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.buildings.models import Building, Unit, UnitClassification, UnitStatus
from apps.payments.management.commands import reconcile_matasia_commercial as cmd
from apps.payments.models import Arrears, Payment, UtilityCharge
from apps.payments.monthly_ledger import build_monthly_ledger
from apps.tenants.models import Tenant, TenantStatus

D = Decimal


@pytest.fixture
def arcade(db):
    building = Building.objects.create(name="Matasia Arcade", code="MCT", total_floors=2)

    def let(label, rent):
        unit = Unit.objects.create(
            building=building, label=label, monthly_rent=D(rent),
            classification=UnitClassification.BUSINESS, status=UnitStatus.OCCUPIED_UNPAID,
        )
        return Tenant.objects.create(
            first_name=label, last_name="Ltd", id_number=f"T-{label}",
            phone="+254700000002", unit=unit, monthly_rent=D(rent),
            deposit_paid=D(0), move_in_date="2026-07-21", status=TenantStatus.ACTIVE,
        )

    return {"owing": let("MCT01", "24000"), "credit": let("MCT13", "24000")}


def _stmt(monkeypatch, rows, occupancy=()):
    monkeypatch.setattr(cmd, "STATEMENT", rows)
    monkeypatch.setattr(cmd, "OCCUPANCY_QUERIES", list(occupancy))


def _row(tenant, bf, rent, vat, other=0, label=""):
    return (tenant.unit.label, tenant.pk, D(bf), D(rent), D(vat), D(other), label)


def _july(tenant):
    return Arrears.objects.filter(tenant=tenant, period_year=2026, period_month=7).first()


def _august(tenant):
    return Arrears.objects.filter(tenant=tenant, period_year=2026, period_month=8).first()


class TestPreflight:
    def test_aborts_when_the_id_is_on_another_unit(self, arcade, monkeypatch):
        row = _row(arcade["owing"], 12000, 24000, 3840)
        _stmt(monkeypatch, [("MCT99", row[1], *row[2:])])

        with pytest.raises(CommandError, match="Pre-flight failed"):
            call_command("reconcile_matasia_commercial", "--apply")

    def test_writes_nothing_when_preflight_fails(self, arcade, monkeypatch):
        good = _row(arcade["owing"], 12000, 24000, 3840)
        bad = _row(arcade["credit"], -1000, 24000, 3840)
        _stmt(monkeypatch, [good, ("MCT99", bad[1], *bad[2:])])

        with pytest.raises(CommandError):
            call_command("reconcile_matasia_commercial", "--apply")

        assert _july(arcade["owing"]) is None, "a valid row was written despite the abort"


class TestOpeningPosition:
    def test_positive_brought_forward_becomes_a_july_charge(self, arcade, monkeypatch):
        _stmt(monkeypatch, [_row(arcade["owing"], 12000, 24000, 3840)])

        call_command("reconcile_matasia_commercial", "--apply")

        jul = _july(arcade["owing"])
        assert jul.expected_rent == D("12000.00")
        assert jul.expected_vat == D("0.00"), "VAT re-charged on a carried-forward figure"

    def test_negative_brought_forward_becomes_an_opening_credit(self, arcade, monkeypatch):
        _stmt(monkeypatch, [_row(arcade["credit"], -27840, 24000, 3840)])

        call_command("reconcile_matasia_commercial", "--apply")

        jul = _july(arcade["credit"])
        assert jul.expected_rent == D("0.00")
        credit = Payment.objects.get(tenant=arcade["credit"], period_month=7, voided_at__isnull=True)
        assert credit.amount == D("27840.00")
        assert credit.payment_date == _dt.date(2026, 7, 31)

    def test_credit_carries_into_august_as_a_negative_balance(self, arcade, monkeypatch):
        """The statement nets MCF13 to zero: -27,840 + 24,000 + 3,840 = 0."""
        _stmt(monkeypatch, [_row(arcade["credit"], -27840, 24000, 3840)])

        call_command("reconcile_matasia_commercial", "--apply")

        rows = {r["period"]: r for r in build_monthly_ledger(arcade["credit"], today=_dt.date(2026, 8, 26))}
        assert Decimal(rows["7/2026"]["balance"]) == D("-27840.00")
        assert Decimal(rows["8/2026"]["total_due"]) == D("0.00")

    def test_zero_brought_forward_creates_nothing(self, arcade, monkeypatch):
        _stmt(monkeypatch, [_row(arcade["owing"], 0, 24000, 3840)])

        call_command("reconcile_matasia_commercial", "--apply")

        assert _july(arcade["owing"]) is None

    def test_an_existing_july_row_is_never_overwritten(self, arcade, monkeypatch):
        Arrears.objects.create(
            tenant=arcade["owing"], period_year=2026, period_month=7,
            expected_rent=D("24000"), expected_vat=D("3840"),
            amount_paid=D(0), balance=D("27840"),
        )
        _stmt(monkeypatch, [_row(arcade["owing"], 12000, 24000, 3840)])

        call_command("reconcile_matasia_commercial", "--apply")

        assert _july(arcade["owing"]).expected_rent == D("24000.00"), "a real billed month was clobbered"


class TestAugustCharge:
    def test_sets_rent_and_vat(self, arcade, monkeypatch):
        _stmt(monkeypatch, [_row(arcade["owing"], 0, 24000, 3840)])

        call_command("reconcile_matasia_commercial", "--apply")

        aug = _august(arcade["owing"])
        assert (aug.expected_rent, aug.expected_vat) == (D("24000.00"), D("3840.00"))

    def test_corrects_a_row_billed_at_the_wrong_figure(self, arcade, monkeypatch):
        Arrears.objects.create(
            tenant=arcade["owing"], period_year=2026, period_month=8,
            expected_rent=D("0"), expected_vat=D("0"), amount_paid=D(0), balance=D(0),
        )
        _stmt(monkeypatch, [_row(arcade["owing"], 0, 24000, 3840)])

        call_command("reconcile_matasia_commercial", "--apply")

        aug = _august(arcade["owing"])
        assert (aug.expected_rent, aug.expected_vat) == (D("24000.00"), D("3840.00"))

    def test_statement_zero_vat_is_respected(self, arcade, monkeypatch):
        """MCG02 is billed 22,500 with no VAT on the sheet. Honour the sheet."""
        _stmt(monkeypatch, [_row(arcade["owing"], 0, 22500, 0)])

        call_command("reconcile_matasia_commercial", "--apply")

        assert _august(arcade["owing"]).expected_vat == D("0.00")


class TestOtherCharges:
    def test_posts_other_costs(self, arcade, monkeypatch):
        _stmt(monkeypatch, [_row(arcade["owing"], 0, 18000, 2880, other=1360, label="Other costs")])

        call_command("reconcile_matasia_commercial", "--apply")

        charge = UtilityCharge.objects.get(tenant=arcade["owing"], period_month=8)
        assert charge.amount == D("1360.00")

    def test_nothing_posted_when_the_statement_says_zero(self, arcade, monkeypatch):
        _stmt(monkeypatch, [_row(arcade["owing"], 0, 24000, 3840, other=0)])

        call_command("reconcile_matasia_commercial", "--apply")

        assert not UtilityCharge.objects.filter(tenant=arcade["owing"]).exists()

    def test_a_conflicting_existing_charge_is_left_for_review(self, arcade, monkeypatch):
        UtilityCharge.objects.create(
            tenant=arcade["owing"], posting_date=_dt.date(2026, 8, 1),
            period_year=2026, period_month=8, label="Water", amount=D("900"),
        )
        _stmt(monkeypatch, [_row(arcade["owing"], 0, 18000, 2880, other=1360)])

        call_command("reconcile_matasia_commercial", "--apply")

        charges = UtilityCharge.objects.filter(tenant=arcade["owing"], period_month=8)
        assert charges.count() == 1 and charges.get().amount == D("900.00")


class TestIdempotence:
    def test_rerun_changes_nothing(self, arcade, monkeypatch):
        _stmt(monkeypatch, [_row(arcade["owing"], 12000, 24000, 3840, other=1360)])

        call_command("reconcile_matasia_commercial", "--apply")
        call_command("reconcile_matasia_commercial", "--apply")

        assert Arrears.objects.filter(tenant=arcade["owing"]).count() == 2
        assert UtilityCharge.objects.filter(tenant=arcade["owing"]).count() == 1

    def test_credit_rerun_does_not_double_book(self, arcade, monkeypatch):
        _stmt(monkeypatch, [_row(arcade["credit"], -3900, 22500, 3600)])

        call_command("reconcile_matasia_commercial", "--apply")
        call_command("reconcile_matasia_commercial", "--apply")

        assert Payment.objects.filter(tenant=arcade["credit"], voided_at__isnull=True).count() == 1

    def test_dry_run_writes_nothing(self, arcade, monkeypatch):
        _stmt(monkeypatch, [_row(arcade["owing"], 12000, 24000, 3840)])

        call_command("reconcile_matasia_commercial")

        assert _july(arcade["owing"]) is None
        assert _august(arcade["owing"]) is None


class TestReproducesTheStatement:
    def test_mcg01_august_row_matches_the_sheet(self, arcade, monkeypatch):
        """The whole point of the exercise.

        Statement MCG01: b/f 12,000 · rent 24,000 · VAT 3,840 · other 0
        · total payable 39,840 · paid 27,840 · balance 12,000.
        """
        from apps.payments.services import process_payment

        tenant = arcade["owing"]
        _stmt(monkeypatch, [_row(tenant, 12000, 24000, 3840)])
        call_command("reconcile_matasia_commercial", "--apply")

        process_payment(
            tenant=tenant, amount=D("27840"), payment_date=_dt.date(2026, 8, 4),
            period_month=8, period_year=2026, source="mpesa",
            reference="CB0347103_04082026_2", idempotency_key="CB0347103_04082026_2",
        )

        aug = {r["period"]: r for r in build_monthly_ledger(tenant, today=_dt.date(2026, 8, 26))}["8/2026"]

        assert Decimal(aug["brought_forward"]) == D("12000.00"), "arrears b/f"
        assert Decimal(aug["rent"]) == D("24000.00"), "rent"
        assert Decimal(aug["vat"]) == D("3840.00"), "16% VAT"
        assert Decimal(aug["other_charges"]) == D("0.00"), "other charges"
        assert Decimal(aug["total_due"]) == D("39840.00"), "total payable"
        assert Decimal(aug["paid"]) == D("27840.00"), "payment made"
        assert Decimal(aug["balance"]) == D("12000.00"), "balance"
