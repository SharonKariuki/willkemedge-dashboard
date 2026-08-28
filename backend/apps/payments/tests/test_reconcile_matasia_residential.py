"""
Tests for the Matasia Residential statement cleanup.

The acceptance tests are the last two: after the command runs, the monthly rent
roll must reproduce the landlord's 21-08-2026 rows exactly. MR202 is the one the
owner raised — -2,000 b/f + 20,000 rent + 1,800 water = 19,800 due, 19,800 paid,
nothing owing — and MR304 is the awkward one, where a credit brought forward and
a 4,000 water charge still leave 7,000 outstanding. Everything above them exists
to pin the pieces that get there.
"""
import datetime as _dt
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.buildings.models import Building, Unit, UnitClassification, UnitStatus
from apps.payments.management.commands import reconcile_matasia_residential as cmd
from apps.payments.models import Arrears, Payment, UtilityCharge
from apps.payments.monthly_ledger import build_monthly_ledger
from apps.payments.services import process_payment
from apps.tenants.models import Tenant, TenantStatus

D = Decimal
AUG_21 = _dt.date(2026, 8, 21)


@pytest.fixture
def flats(db):
    building = Building.objects.create(name="Matasia Residential", code="MRT", total_floors=3)

    def let(label, rent):
        unit = Unit.objects.create(
            building=building, label=label, monthly_rent=D(rent),
            classification=UnitClassification.RESIDENTIAL, status=UnitStatus.OCCUPIED_UNPAID,
        )
        return Tenant.objects.create(
            first_name=label, last_name="Tenant", id_number=f"T-{label}",
            phone="+254700000003", unit=unit, monthly_rent=D(rent),
            deposit_paid=D(0), move_in_date="2026-07-21", status=TenantStatus.ACTIVE,
        )

    return {"owing": let("MRT07", "22000"), "credit": let("MRT02", "20000")}


def _stmt(monkeypatch, rows, vacancies=()):
    monkeypatch.setattr(cmd, "STATEMENT", rows)
    monkeypatch.setattr(cmd, "VACANCY_QUERIES", list(vacancies))


def _row(tenant, bf, rent, other=0, paid=0, unpaid=0):
    return (tenant.unit.label, tenant.pk, D(bf), D(rent), D(other), D(paid), D(unpaid))


def _july(tenant):
    return Arrears.objects.filter(tenant=tenant, period_year=2026, period_month=7).first()


def _august(tenant):
    return Arrears.objects.filter(tenant=tenant, period_year=2026, period_month=8).first()


def _roll(tenant):
    return {
        r["period"]: r
        for r in build_monthly_ledger(tenant, months=0, today=AUG_21)
    }


class TestPreflight:
    def test_aborts_when_the_id_is_on_another_unit(self, flats, monkeypatch):
        row = _row(flats["owing"], 6000, 22000)
        _stmt(monkeypatch, [("MRT99", row[1], *row[2:])])

        with pytest.raises(CommandError, match="Pre-flight failed"):
            call_command("reconcile_matasia_residential", "--apply")

    def test_writes_nothing_when_preflight_fails(self, flats, monkeypatch):
        good = _row(flats["owing"], 6000, 22000)
        bad = _row(flats["credit"], -2000, 20000)
        _stmt(monkeypatch, [good, ("MRT99", bad[1], *bad[2:])])

        with pytest.raises(CommandError):
            call_command("reconcile_matasia_residential", "--apply")

        assert _july(flats["owing"]) is None, "a valid row was written despite the abort"

    def test_a_missing_tenant_is_skipped_not_fatal(self, flats, monkeypatch):
        """A id that is absent may simply be a database this row does not apply to."""
        _stmt(monkeypatch, [("MRT07", 999_999, D(6000), D(22000), D(0), D(0), D(0))])

        call_command("reconcile_matasia_residential", "--apply")

        assert not Arrears.objects.exists()


class TestDryRun:
    def test_writes_nothing_without_apply(self, flats, monkeypatch):
        _stmt(monkeypatch, [_row(flats["owing"], 6000, 22000, other=1000)])

        call_command("reconcile_matasia_residential")

        assert not Arrears.objects.exists()
        assert not UtilityCharge.objects.exists()


class TestOpeningPosition:
    def test_positive_brought_forward_becomes_a_july_charge(self, flats, monkeypatch):
        _stmt(monkeypatch, [_row(flats["owing"], 6000, 22000)])

        call_command("reconcile_matasia_residential", "--apply")

        jul = _july(flats["owing"])
        assert jul.expected_rent == D("6000.00")
        assert jul.expected_vat == D("0.00")

    def test_the_july_row_reads_as_brought_forward_not_as_rent(self, flats, monkeypatch):
        """Without the marker the roll reports a 6,000 month billed at 6,000."""
        _stmt(monkeypatch, [_row(flats["owing"], 6000, 22000)])

        call_command("reconcile_matasia_residential", "--apply")

        jul = _roll(flats["owing"])["7/2026"]
        assert jul["is_opening"] is True
        assert D(jul["rent"]) == D("0.00")
        assert D(jul["brought_forward"]) == D("6000.00")

    def test_negative_brought_forward_becomes_an_opening_credit(self, flats, monkeypatch):
        _stmt(monkeypatch, [_row(flats["credit"], -2000, 20000)])

        call_command("reconcile_matasia_residential", "--apply")

        assert _july(flats["credit"]).expected_rent == D("0.00")
        credit = Payment.objects.get(
            tenant=flats["credit"], period_month=7, voided_at__isnull=True
        )
        assert credit.amount == D("2000.00")
        assert credit.payment_date == _dt.date(2026, 7, 31)

    def test_credit_carries_into_august(self, flats, monkeypatch):
        """MR202: -2,000 b/f + 20,000 rent + 1,800 water = 19,800 due."""
        _stmt(monkeypatch, [_row(flats["credit"], -2000, 20000, other=1800)])

        call_command("reconcile_matasia_residential", "--apply")

        rows = _roll(flats["credit"])
        assert D(rows["7/2026"]["balance"]) == D("-2000.00")
        assert D(rows["8/2026"]["total_due"]) == D("19800.00")

    def test_zero_brought_forward_creates_nothing(self, flats, monkeypatch):
        _stmt(monkeypatch, [_row(flats["owing"], 0, 22000)])

        call_command("reconcile_matasia_residential", "--apply")

        assert _july(flats["owing"]) is None

    def test_an_existing_july_row_is_never_overwritten(self, flats, monkeypatch):
        Arrears.objects.create(
            tenant=flats["owing"], period_year=2026, period_month=7,
            expected_rent=D("22000"), expected_vat=D(0), amount_paid=D(0), balance=D("22000"),
        )
        _stmt(monkeypatch, [_row(flats["owing"], 6000, 22000)])

        call_command("reconcile_matasia_residential", "--apply")

        assert _july(flats["owing"]).expected_rent == D("22000.00"), "a real billed month was clobbered"

    def test_a_july_utility_charge_blocks_the_seed(self, flats, monkeypatch):
        """Seeding a closing position on top of a July charge double-counts it."""
        UtilityCharge.objects.create(
            tenant=flats["owing"], posting_date=_dt.date(2026, 7, 1),
            period_year=2026, period_month=7, label="Water", amount=D("1500"),
        )
        _stmt(monkeypatch, [_row(flats["owing"], 6000, 22000)])

        call_command("reconcile_matasia_residential", "--apply")

        assert _july(flats["owing"]) is None


class TestAugustCharge:
    def test_sets_rent_with_no_vat(self, flats, monkeypatch):
        _stmt(monkeypatch, [_row(flats["owing"], 0, 22000)])

        call_command("reconcile_matasia_residential", "--apply")

        aug = _august(flats["owing"])
        assert (aug.expected_rent, aug.expected_vat) == (D("22000.00"), D("0.00"))

    def test_strips_vat_wrongly_billed_on_a_residential_row(self, flats, monkeypatch):
        Arrears.objects.create(
            tenant=flats["owing"], period_year=2026, period_month=8,
            expected_rent=D("22000"), expected_vat=D("3520"),
            amount_paid=D(0), balance=D("25520"),
        )
        _stmt(monkeypatch, [_row(flats["owing"], 0, 22000)])

        call_command("reconcile_matasia_residential", "--apply")

        assert _august(flats["owing"]).expected_vat == D("0.00")

    def test_corrects_a_row_billed_at_the_wrong_figure(self, flats, monkeypatch):
        Arrears.objects.create(
            tenant=flats["owing"], period_year=2026, period_month=8,
            expected_rent=D("0"), expected_vat=D(0), amount_paid=D(0), balance=D(0),
        )
        _stmt(monkeypatch, [_row(flats["owing"], 0, 22000)])

        call_command("reconcile_matasia_residential", "--apply")

        assert _august(flats["owing"]).expected_rent == D("22000.00")


class TestWaterAndOtherCosts:
    def test_posts_the_water_charge(self, flats, monkeypatch):
        """The owner's MR202 case: 1,800 on the statement, nothing in the system."""
        _stmt(monkeypatch, [_row(flats["credit"], 0, 20000, other=1800)])

        call_command("reconcile_matasia_residential", "--apply")

        charge = UtilityCharge.objects.get(tenant=flats["credit"], period_month=8)
        assert charge.amount == D("1800.00")
        assert charge.label == "Water + Other Costs"
        assert charge.period_year == 2026

    def test_the_charge_lands_in_the_august_total(self, flats, monkeypatch):
        _stmt(monkeypatch, [_row(flats["credit"], 0, 20000, other=1800)])

        call_command("reconcile_matasia_residential", "--apply")

        aug = _roll(flats["credit"])["8/2026"]
        assert D(aug["other_charges"]) == D("1800.00")
        assert D(aug["total_due"]) == D("21800.00")

    def test_nothing_posted_when_the_statement_says_zero(self, flats, monkeypatch):
        _stmt(monkeypatch, [_row(flats["owing"], 0, 22000, other=0)])

        call_command("reconcile_matasia_residential", "--apply")

        assert not UtilityCharge.objects.filter(tenant=flats["owing"]).exists()

    def test_a_conflicting_existing_charge_is_left_for_review(self, flats, monkeypatch):
        UtilityCharge.objects.create(
            tenant=flats["owing"], posting_date=_dt.date(2026, 8, 1),
            period_year=2026, period_month=8, label="Water", amount=D("900"),
        )
        _stmt(monkeypatch, [_row(flats["owing"], 0, 22000, other=1000)])

        call_command("reconcile_matasia_residential", "--apply")

        charges = UtilityCharge.objects.filter(tenant=flats["owing"], period_month=8)
        assert charges.count() == 1 and charges.get().amount == D("900.00")


class TestVerification:
    def _pay(self, tenant, amount):
        process_payment(
            tenant=tenant, amount=D(amount), payment_date=AUG_21,
            period_month=8, period_year=2026, source="bank",
            reference=f"AUG-{tenant.pk}", idempotency_key=f"AUG-{tenant.pk}",
        )

    def test_reports_a_row_that_reconciles(self, flats, monkeypatch, capsys):
        _stmt(monkeypatch, [_row(flats["credit"], -2000, 20000, other=1800, paid=19800)])
        call_command("reconcile_matasia_residential", "--apply")
        self._pay(flats["credit"], 19800)

        call_command("reconcile_matasia_residential", "--apply")

        assert "ok    MRT02" in capsys.readouterr().out

    def test_reports_missing_cash_rather_than_inventing_it(self, flats, monkeypatch, capsys):
        """The statement says 22,000 was paid; the feed has none of it."""
        _stmt(monkeypatch, [_row(flats["owing"], 0, 22000, paid=22000)])

        call_command("reconcile_matasia_residential", "--apply")

        out = capsys.readouterr().out
        assert "paid 0.00 vs statement 22000.00" in out
        assert not Payment.objects.filter(tenant=flats["owing"], period_month=8).exists()


class TestVacancyQueries:
    def test_reports_a_unit_the_statement_dropped(self, flats, monkeypatch, capsys):
        _stmt(monkeypatch, [], vacancies=[("MRT07", "absent from the 21 Aug statement")])

        call_command("reconcile_matasia_residential")

        assert "MRT07" in capsys.readouterr().out

    def test_an_unknown_unit_is_skipped(self, flats, monkeypatch, capsys):
        _stmt(monkeypatch, [], vacancies=[("MRT99", "gone")])

        call_command("reconcile_matasia_residential")

        assert "not in the database" in capsys.readouterr().out


class TestIdempotence:
    def test_rerun_changes_nothing(self, flats, monkeypatch):
        _stmt(monkeypatch, [_row(flats["owing"], 6000, 22000, other=1000)])

        call_command("reconcile_matasia_residential", "--apply")
        call_command("reconcile_matasia_residential", "--apply")

        assert Arrears.objects.filter(tenant=flats["owing"]).count() == 2
        assert UtilityCharge.objects.filter(tenant=flats["owing"]).count() == 1

    def test_credit_rerun_does_not_double_book(self, flats, monkeypatch):
        _stmt(monkeypatch, [_row(flats["credit"], -2000, 20000)])

        call_command("reconcile_matasia_residential", "--apply")
        call_command("reconcile_matasia_residential", "--apply")

        credits = Payment.objects.filter(tenant=flats["credit"], period_month=7)
        assert credits.count() == 1


class TestAcceptance:
    """The rebuilt roll must reproduce the landlord's statement rows."""

    def test_mr202_marion_munyinyi(self, flats, monkeypatch):
        """-2,000 b/f + 20,000 rent + 1,800 water = 19,800 due, 19,800 paid, 0 owing."""
        _stmt(monkeypatch, [_row(flats["credit"], -2000, 20000, other=1800, paid=19800)])
        call_command("reconcile_matasia_residential", "--apply")
        process_payment(
            tenant=flats["credit"], amount=D("19800"), payment_date=AUG_21,
            period_month=8, period_year=2026, source="bank",
            reference="MR202-AUG", idempotency_key="MR202-AUG",
        )

        aug = _roll(flats["credit"])["8/2026"]
        assert D(aug["brought_forward"]) == D("-2000.00")
        assert D(aug["rent"]) == D("20000.00")
        assert D(aug["vat"]) == D("0.00")
        assert D(aug["other_charges"]) == D("1800.00")
        assert D(aug["total_due"]) == D("19800.00")
        assert D(aug["paid"]) == D("19800.00")
        assert D(aug["balance"]) == D("0.00")

    def test_mr304_mercy_timona(self, flats, monkeypatch):
        """A credit brought forward that still leaves 7,000 owing.

        -8,000 b/f + 12,000 rent + 4,000 water = 8,000 due, 1,000 paid, 7,000 owing.
        """
        tenant = flats["owing"]
        _stmt(monkeypatch, [_row(tenant, -8000, 12000, other=4000, paid=1000, unpaid=7000)])
        call_command("reconcile_matasia_residential", "--apply")
        process_payment(
            tenant=tenant, amount=D("1000"), payment_date=AUG_21,
            period_month=8, period_year=2026, source="mpesa",
            reference="MR304-AUG", idempotency_key="MR304-AUG",
        )

        aug = _roll(tenant)["8/2026"]
        assert D(aug["total_due"]) == D("8000.00")
        assert D(aug["paid"]) == D("1000.00")
        assert D(aug["balance"]) == D("7000.00")
