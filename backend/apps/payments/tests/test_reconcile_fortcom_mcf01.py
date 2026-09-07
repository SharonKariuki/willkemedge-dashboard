"""
Tests for the Fortcom (MCF01) reconciliation.

The fixture is the production shape as found on 7 Sept 2026: a 75,000 credit
mis-read as three months' rent, and a later 32,000 credit that FIFO then spread
over the three periods the first mis-read had created. Both have to be re-cut
together — that is the whole reason this tenancy has its own command.

The acceptance test is the last one: August cleared, September 1,000 short,
October gone, and the 50,000 deposit sitting outside the rent balance entirely.
"""
import datetime as _dt
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.buildings.models import Building, Unit, UnitClassification, UnitStatus
from apps.payments.management.commands import reconcile_fortcom_mcf01 as cmd
from apps.payments.models import Arrears, Payment, PaymentType
from apps.tenants.models import Tenant, TenantStatus

D = Decimal

REF1 = "S48023247_10082026_2"
REF2 = "CB0289926_05092026_1"


@pytest.fixture(autouse=True)
def cycle_on_september(monkeypatch):
    """Pin the billing cycle to September.

    Whether October may be dropped turns on the calendar, so leaving it to the
    wall clock would make this file start failing on 25 September.
    """
    from apps.payments import billing_calendar

    monkeypatch.setattr(billing_calendar, "billing_period", lambda *a, **k: (2026, 9))


@pytest.fixture
def fortcom(db, monkeypatch):
    """MCF01 exactly as production held it on 7 Sept 2026."""
    from apps.payments.services import process_payment

    building = Building.objects.create(name="Matasia Arcade", code="MCR", total_floors=2)
    unit = Unit.objects.create(
        building=building, label="MCF01", monthly_rent=D("25000"),
        classification=UnitClassification.BUSINESS, status=UnitStatus.OCCUPIED_UNPAID,
    )
    tenant = Tenant.objects.create(
        first_name="Fortcom Realtors", last_name="Limited", id_number="R-MCF01",
        phone="+254794969696", unit=unit, monthly_rent=D("25000"),
        deposit_paid=D("50000"), move_in_date="2026-08-10", status=TenantStatus.ACTIVE,
    )
    monkeypatch.setattr(cmd, "TENANT_ID", tenant.pk)

    # The 75,000, read as three months' rent.
    for i, month in enumerate((8, 9, 10)):
        process_payment(
            tenant=tenant, amount=D("25000"), payment_date=_dt.date(2026, 8, 10),
            period_month=month, period_year=2026, source="bank",
            reference=REF1, idempotency_key=f"{REF1}#{i}",
        )
    # The 32,000, FIFO'd across the periods that mis-read had created.
    for i, (amount, month) in enumerate(
        ((D("4000"), 8), (D("4000"), 9), (D("4000"), 10), (D("20000"), 9))
    ):
        process_payment(
            tenant=tenant, amount=amount, payment_date=_dt.date(2026, 9, 5),
            period_month=month, period_year=2026, source="bank",
            reference=REF2, idempotency_key=f"{REF2}#{i}",
        )
    return tenant


def _arr(tenant, month):
    return Arrears.objects.filter(tenant=tenant, period_year=2026, period_month=month).first()


def _live(tenant, ref=None):
    qs = Payment.objects.filter(tenant=tenant, voided_at__isnull=True)
    return qs.filter(reference=ref) if ref else qs


def _shape(tenant, ref):
    return {
        (p.amount, p.payment_type, p.period_month) for p in _live(tenant, ref)
    }


class TestThePlan:
    """The figures come from a PDF and a bank feed, so they are checked as data
    before any of them is written."""

    def test_every_allocation_totals_the_money_banked(self):
        for ref, _d, _s, banked, parts, _w in cmd.CREDITS:
            assert sum((a for a, _k, _p in parts), D(0)) == banked, ref

    def test_the_statement_summary_foots(self):
        assert cmd.SUMMARY_ARREARS + cmd.SUMMARY_CURRENT == cmd.TOTAL_DUE

    def test_what_is_owed_is_the_statement_less_what_came_after_it(self):
        """Two routes to the same number: charges less rent cash, and the
        statement's total less the payment that followed it."""
        assert cmd.outstanding() == cmd.TOTAL_DUE - cmd.paid_since_the_statement()

    def test_the_deposit_is_whole_months_of_rent(self):
        assert cmd.DEPOSIT == cmd.RENT * cmd.DEPOSIT_MONTHS

    def test_the_deposit_is_not_counted_as_rent(self):
        rent = cmd.rent_allocated()
        banked = sum((b for _r, _d, _s, b, _p, _w in cmd.CREDITS), D(0))
        assert banked - rent == cmd.DEPOSIT


class TestPreflight:
    def test_aborts_when_the_id_is_on_another_unit(self, fortcom):
        other = Unit.objects.create(
            building=fortcom.unit.building, label="MCF09", monthly_rent=D("25000"),
            classification=UnitClassification.BUSINESS, status=UnitStatus.OCCUPIED_UNPAID,
        )
        fortcom.unit = other
        fortcom.save(update_fields=["unit"])

        with pytest.raises(CommandError, match="Pre-flight failed"):
            call_command("reconcile_fortcom_mcf01", "--apply")

    def test_aborts_when_the_tenant_is_not_there(self, fortcom, monkeypatch):
        monkeypatch.setattr(cmd, "TENANT_ID", fortcom.pk + 9999)

        with pytest.raises(CommandError, match="not found"):
            call_command("reconcile_fortcom_mcf01", "--apply")

    def test_aborts_when_an_allocation_does_not_add_up(self, fortcom, monkeypatch):
        """A transcription slip in the parts would quietly invent or lose money."""
        monkeypatch.setattr(cmd, "CREDITS", [(
            REF1, _dt.date(2026, 8, 10), "bank", D("75000"),
            [(D("50000"), "deposit", (2026, 8))], "short by a part",
        )])

        with pytest.raises(CommandError, match="does not add up"):
            call_command("reconcile_fortcom_mcf01", "--apply")

        assert _shape(fortcom, REF1) == {
            (D("25000.00"), "rent", 8), (D("25000.00"), "rent", 9), (D("25000.00"), "rent", 10),
        }, "the mis-split was touched despite the abort"


class TestRecuttingTheCredits:
    def test_the_75k_becomes_a_deposit_plus_august_rent(self, fortcom):
        call_command("reconcile_fortcom_mcf01", "--apply")

        assert _shape(fortcom, REF1) == {
            (D("50000.00"), "deposit", 8),
            (D("25000.00"), "rent", 8),
        }

    def test_the_32k_moves_off_the_periods_the_mis_split_invented(self, fortcom):
        call_command("reconcile_fortcom_mcf01", "--apply")

        assert _shape(fortcom, REF2) == {
            (D("4000.00"), "rent", 8),
            (D("28000.00"), "rent", 9),
        }

    def test_neither_amount_banked_is_changed(self, fortcom):
        """A reconciliation redistributes; it must never invent or lose money."""
        call_command("reconcile_fortcom_mcf01", "--apply")

        for ref, banked in ((REF1, D("75000.00")), (REF2, D("32000.00"))):
            assert sum((p.amount for p in _live(fortcom, ref)), D(0)) == banked, ref

    def test_the_originals_stay_in_the_ledger_as_voids(self, fortcom):
        """Payments are immutable. The correction is a void plus a replacement,
        so the receipt and its reversal both remain."""
        call_command("reconcile_fortcom_mcf01", "--apply")

        assert Payment.objects.filter(tenant=fortcom, voided_at__isnull=False).count() == 7

    def test_refuses_when_the_reference_holds_a_different_sum(self, fortcom, monkeypatch):
        monkeypatch.setattr(cmd, "CREDITS", [(
            REF1, _dt.date(2026, 8, 10), "bank", D("60000"),
            [(D("60000"), "rent", (2026, 8))], "wrong idea of what was banked",
        )])

        call_command("reconcile_fortcom_mcf01")

        assert _shape(fortcom, REF1) == {
            (D("25000.00"), "rent", 8), (D("25000.00"), "rent", 9), (D("25000.00"), "rent", 10),
        }

    def test_is_idempotent(self, fortcom):
        call_command("reconcile_fortcom_mcf01", "--apply")
        after_one = _live(fortcom).count()

        call_command("reconcile_fortcom_mcf01", "--apply")

        assert _live(fortcom).count() == after_one

    def test_names_a_credit_it_does_not_know_about(self, fortcom, capsys):
        """An unexpected receipt would otherwise show up only as a total that
        does not tie."""
        from apps.payments.services import process_payment

        process_payment(
            tenant=fortcom, amount=D("5000"), payment_date=_dt.date(2026, 9, 6),
            period_month=9, period_year=2026, source="mpesa",
            reference="LATE-ARRIVAL", idempotency_key="LATE-ARRIVAL",
        )

        call_command("reconcile_fortcom_mcf01")

        assert "LATE-ARRIVAL" in capsys.readouterr().out


class TestDeposit:
    def test_records_the_two_month_agreement(self, fortcom):
        call_command("reconcile_fortcom_mcf01", "--apply")

        fortcom.refresh_from_db()
        assert fortcom.agreed_deposit == D("50000.00")

    def test_the_three_month_rule_stops_reporting_a_shortfall(self, fortcom):
        """The whole point: 50,000 against a 75,000 rule reads as 25,000 owed,
        and the statement says it is paid in full."""
        from apps.tenants.deposits import deposit_shortfall

        assert deposit_shortfall(fortcom) == D("25000.00")

        call_command("reconcile_fortcom_mcf01", "--apply")

        fortcom.refresh_from_db()
        assert deposit_shortfall(fortcom) == D("0.00")

    def test_reconciles_what_was_received_once_the_credit_is_re_cut(self, fortcom):
        Tenant.objects.filter(pk=fortcom.pk).update(deposit_paid=D(0))

        call_command("reconcile_fortcom_mcf01", "--apply")

        fortcom.refresh_from_db()
        assert fortcom.deposit_paid == D("50000.00")

    def test_the_note_is_not_appended_twice(self, fortcom):
        call_command("reconcile_fortcom_mcf01", "--apply")
        fortcom.refresh_from_db()
        notes = fortcom.notes

        call_command("reconcile_fortcom_mcf01", "--apply")

        fortcom.refresh_from_db()
        assert fortcom.notes == notes


class TestOctober:
    def test_is_dropped_once_the_cash_has_moved_off_it(self, fortcom):
        assert _arr(fortcom, 10) is not None

        call_command("reconcile_fortcom_mcf01", "--apply")

        assert _arr(fortcom, 10) is None

    def test_is_kept_while_cash_still_sits_against_it(self, fortcom, monkeypatch):
        """Dropping it first would strand the 4,000 on a period with nothing
        left to settle."""
        monkeypatch.setattr(cmd, "CREDITS", [])

        call_command("reconcile_fortcom_mcf01")

        assert _arr(fortcom, 10) is not None

    def test_is_kept_once_the_biller_has_reached_it(self, fortcom, monkeypatch):
        """From 25 September the cron raises October itself. Dropping it then
        only gets it re-raised on the next run."""
        from apps.payments import billing_calendar

        monkeypatch.setattr(billing_calendar, "billing_period", lambda *a, **k: (2026, 10))

        with pytest.raises(CommandError, match="did not foot"):
            call_command("reconcile_fortcom_mcf01", "--apply")

        assert _arr(fortcom, 10) is not None


class TestDryRun:
    def test_writes_nothing(self, fortcom):
        call_command("reconcile_fortcom_mcf01")

        fortcom.refresh_from_db()
        assert fortcom.agreed_deposit is None
        assert _arr(fortcom, 10) is not None
        assert _shape(fortcom, REF1) == {
            (D("25000.00"), "rent", 8), (D("25000.00"), "rent", 9), (D("25000.00"), "rent", 10),
        }


class TestItFoots:
    def test_reproduces_the_position(self, fortcom):
        """The acceptance test. August cleared by 25,000 + 4,000, September
        holding 28,000 against 29,000, October gone."""
        call_command("reconcile_fortcom_mcf01", "--apply")

        assert _arr(fortcom, 8).amount_paid == D("29000.00")
        assert _arr(fortcom, 8).balance == D("0.00")
        assert _arr(fortcom, 9).amount_paid == D("28000.00")
        assert _arr(fortcom, 9).balance == D("1000.00")
        assert _arr(fortcom, 10) is None

    def test_the_shortfall_is_the_statement_less_what_they_paid(self, fortcom):
        call_command("reconcile_fortcom_mcf01", "--apply")

        assert _arr(fortcom, 9).balance == cmd.TOTAL_DUE - cmd.paid_since_the_statement()

    def test_the_deposit_never_settles_rent(self, fortcom):
        """50,000 of the 75,000 banked is a liability, not income. If it ever
        starts paying rent down, August over-clears and September vanishes."""
        call_command("reconcile_fortcom_mcf01", "--apply")

        deposits = _live(fortcom).filter(payment_type=PaymentType.DEPOSIT)
        assert sum((p.amount for p in deposits), D(0)) == D("50000.00")
        assert _arr(fortcom, 8).amount_paid == D("29000.00"), "the deposit settled rent"

    def test_refuses_to_pass_when_the_books_do_not_tie(self, fortcom, monkeypatch):
        """Better to fail loudly than to report a reconciled tenancy that is not."""
        monkeypatch.setattr(cmd, "CHARGES", [((2026, 8), D("25000"), D("4000"))])

        with pytest.raises(CommandError, match="did not foot"):
            call_command("reconcile_fortcom_mcf01", "--apply")

    def test_a_dry_run_reports_the_gap_without_raising(self, fortcom):
        """Nothing has been written yet, so there is nothing to fail over — the
        run is describing the position it is about to fix."""
        call_command("reconcile_fortcom_mcf01")
