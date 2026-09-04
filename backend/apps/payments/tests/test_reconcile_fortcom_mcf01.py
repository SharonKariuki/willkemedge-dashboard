"""
Tests for the Fortcom (MCF01) reconciliation.

The acceptance test is the last one: after the command runs, Fortcom's rent
balance must be the 33,000 on the 1 Sept 2026 statement — with the 50,000
deposit sitting outside it, because a deposit is a refundable liability and
never settles rent.

Everything above it pins one of the two things this reconciliation actually
changes: the two-month deposit agreement, and September's charge.
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


@pytest.fixture
def fortcom(db, monkeypatch):
    """MCF01 as the books hold it after ``apply_matasia_answers``: August
    billed and part paid, the deposit banked, September not yet raised."""
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
    return tenant


def _bill_august(tenant):
    Arrears.objects.create(
        tenant=tenant, period_year=2026, period_month=8,
        expected_rent=D("25000"), expected_vat=D("4000"),
        amount_paid=D(0), balance=D("29000"), is_cleared=False,
    )


def _the_75k(tenant, *, deposit="50000", rent="25000"):
    """The 10 Aug credit as ``apply_matasia_answers`` leaves it — a deposit and
    a month's rent, both under the one bank reference."""
    from apps.payments.services import process_payment

    for amount, kind in ((deposit, PaymentType.DEPOSIT), (rent, PaymentType.RENT)):
        if D(amount) <= 0:
            continue
        process_payment(
            tenant=tenant, amount=D(amount), payment_date=_dt.date(2026, 8, 10),
            period_month=8, period_year=2026, source="bank",
            reference=cmd.BANK_REF, idempotency_key=f"{cmd.BANK_REF}#{kind}",
            payment_type=kind,
        )


def _arr(tenant, month):
    return Arrears.objects.filter(tenant=tenant, period_year=2026, period_month=month).first()


class TestTheStatementItself:
    """The figures are transcribed from a PDF, so they get checked as data
    before anything is written from them."""

    def test_the_ledger_foots_to_the_total_due(self):
        balance = sum(
            (invoice - payment for _d, _desc, invoice, payment in cmd.LEDGER), D(0)
        )
        assert balance == cmd.TOTAL_DUE

    def test_the_summary_box_foots_to_the_same_total(self):
        assert cmd.SUMMARY_ARREARS + cmd.SUMMARY_CURRENT == cmd.TOTAL_DUE

    def test_the_periods_close_at_the_total_due(self):
        assert sum((closing for _p, _r, _v, closing in cmd.PERIODS), D(0)) == cmd.TOTAL_DUE

    def test_the_deposit_and_the_cash_that_paid_it_cancel(self):
        """Why the books' rent-side balance is the statement's total even though
        the books keep the deposit out of it entirely."""
        charged = sum((rent + vat for _p, rent, vat, _c in cmd.PERIODS), D(0))
        rent_received = cmd.BANKED - cmd.DEPOSIT
        assert charged - rent_received == cmd.TOTAL_DUE

    def test_the_deposit_is_whole_months_of_rent(self):
        assert cmd.DEPOSIT == cmd.RENT * cmd.DEPOSIT_MONTHS


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

    def test_writes_nothing_when_preflight_fails(self, fortcom, monkeypatch):
        monkeypatch.setattr(cmd, "TENANT_ID", fortcom.pk + 9999)

        with pytest.raises(CommandError):
            call_command("reconcile_fortcom_mcf01", "--apply")

        assert _arr(fortcom, 9) is None


class TestDeposit:
    def test_records_the_two_month_agreement(self, fortcom):
        _bill_august(fortcom)
        _the_75k(fortcom)

        call_command("reconcile_fortcom_mcf01", "--apply")

        fortcom.refresh_from_db()
        assert fortcom.agreed_deposit == D("50000.00")

    def test_the_three_month_rule_stops_reporting_a_shortfall(self, fortcom):
        """The whole point: 50,000 against a 75,000 rule reads as 25,000 owed,
        and the statement says it is paid in full."""
        from apps.tenants.deposits import deposit_shortfall

        _bill_august(fortcom)
        _the_75k(fortcom)
        assert deposit_shortfall(fortcom) == D("25000.00")

        call_command("reconcile_fortcom_mcf01", "--apply")

        fortcom.refresh_from_db()
        assert deposit_shortfall(fortcom) == D("0.00")

    def test_what_was_received_is_not_touched_by_the_agreement(self, fortcom):
        """``deposit_paid`` records cash. The agreement is a separate fact and
        must not be written over it."""
        _bill_august(fortcom)
        _the_75k(fortcom)

        call_command("reconcile_fortcom_mcf01", "--apply")

        fortcom.refresh_from_db()
        assert fortcom.deposit_paid == D("50000.00")

    def test_reconciles_what_was_received_to_the_deposit_banked(self, fortcom):
        Tenant.objects.filter(pk=fortcom.pk).update(deposit_paid=D(0))
        fortcom.refresh_from_db()
        _bill_august(fortcom)
        _the_75k(fortcom)

        call_command("reconcile_fortcom_mcf01", "--apply")

        fortcom.refresh_from_db()
        assert fortcom.deposit_paid == D("50000.00")

    def test_leaves_deposit_paid_alone_until_the_credit_is_split(self, fortcom):
        """Cutting the 75,000 into a deposit and a month's rent belongs to
        ``apply_matasia_answers``. Recording a deposit here that no payment
        backs would count the same money twice.

        Un-split, the whole 75,000 settles rent and August clears, so the run
        also cannot foot — which is the right answer: this reconciliation has a
        prerequisite and says so rather than reporting a tenancy it has not
        actually settled."""
        Tenant.objects.filter(pk=fortcom.pk).update(deposit_paid=D(0))
        fortcom.refresh_from_db()
        _bill_august(fortcom)
        _the_75k(fortcom, deposit="0", rent="75000")

        with pytest.raises(CommandError, match="did not foot"):
            call_command("reconcile_fortcom_mcf01", "--apply")

        fortcom.refresh_from_db()
        assert fortcom.deposit_paid == D("0.00")

    def test_is_idempotent(self, fortcom):
        _bill_august(fortcom)
        _the_75k(fortcom)

        call_command("reconcile_fortcom_mcf01", "--apply")
        fortcom.refresh_from_db()
        notes = fortcom.notes

        call_command("reconcile_fortcom_mcf01", "--apply")

        fortcom.refresh_from_db()
        assert fortcom.agreed_deposit == D("50000.00")
        assert fortcom.notes == notes, "the deposit note was appended twice"


class TestSeptember:
    def test_raises_the_charge_the_statement_makes(self, fortcom):
        _bill_august(fortcom)
        _the_75k(fortcom)

        call_command("reconcile_fortcom_mcf01", "--apply")

        sep = _arr(fortcom, 9)
        assert (sep.expected_rent, sep.expected_vat) == (D("25000.00"), D("4000.00"))
        assert sep.balance == D("29000.00")

    def test_leaves_a_charge_the_biller_already_raised(self, fortcom):
        """From 25 August the cron raises September itself, at the same figures.
        The command must find nothing to do rather than rewrite it."""
        _bill_august(fortcom)
        _the_75k(fortcom)
        Arrears.objects.create(
            tenant=fortcom, period_year=2026, period_month=9,
            expected_rent=D("25000"), expected_vat=D("4000"),
            amount_paid=D(0), balance=D("29000"), is_cleared=False,
        )
        raised = _arr(fortcom, 9).pk

        call_command("reconcile_fortcom_mcf01", "--apply")

        assert _arr(fortcom, 9).pk == raised

    def test_corrects_a_charge_that_disagrees_with_the_statement(self, fortcom):
        """A September left at rent with no VAT — the shape the mis-split's
        re-derivation leaves behind."""
        _bill_august(fortcom)
        _the_75k(fortcom)
        Arrears.objects.create(
            tenant=fortcom, period_year=2026, period_month=9,
            expected_rent=D("25000"), expected_vat=D(0),
            amount_paid=D(0), balance=D("25000"), is_cleared=False,
        )

        call_command("reconcile_fortcom_mcf01", "--apply")

        sep = _arr(fortcom, 9)
        assert (sep.expected_rent, sep.expected_vat) == (D("25000.00"), D("4000.00"))


class TestDryRun:
    def test_writes_nothing(self, fortcom):
        _bill_august(fortcom)
        _the_75k(fortcom)

        call_command("reconcile_fortcom_mcf01")

        fortcom.refresh_from_db()
        assert fortcom.agreed_deposit is None
        assert _arr(fortcom, 9) is None


class TestItFoots:
    def test_reproduces_the_statement(self, fortcom):
        """The acceptance test. August closes owing its VAT, September closes
        owing rent and VAT, and the two make the statement's 33,000."""
        _bill_august(fortcom)
        _the_75k(fortcom)

        call_command("reconcile_fortcom_mcf01", "--apply")

        assert _arr(fortcom, 8).balance == cmd.SUMMARY_ARREARS
        assert _arr(fortcom, 9).balance == cmd.SUMMARY_CURRENT
        assert _arr(fortcom, 8).balance + _arr(fortcom, 9).balance == cmd.TOTAL_DUE

    def test_the_deposit_never_settles_rent(self, fortcom):
        """50,000 of the 75,000 banked is a liability, not income. If it ever
        starts paying rent down, August clears and the 4,000 VAT disappears."""
        _bill_august(fortcom)
        _the_75k(fortcom)

        call_command("reconcile_fortcom_mcf01", "--apply")

        assert _arr(fortcom, 8).amount_paid == D("25000.00")
        deposits = Payment.objects.filter(
            tenant=fortcom, payment_type=PaymentType.DEPOSIT, voided_at__isnull=True,
        )
        assert sum((p.amount for p in deposits), D(0)) == D("50000.00")

    def test_refuses_to_pass_when_the_books_do_not_tie(self, fortcom):
        """A stray rent payment clears August, so the tenancy no longer owes the
        statement's 33,000. Better to fail loudly than to report a reconciled
        tenancy that is not."""
        _bill_august(fortcom)
        _the_75k(fortcom)
        from apps.payments.services import process_payment

        process_payment(
            tenant=fortcom, amount=D("4000"), payment_date=_dt.date(2026, 8, 30),
            period_month=8, period_year=2026, source="mpesa",
            reference="STRAY", idempotency_key="STRAY",
        )

        with pytest.raises(CommandError, match="did not foot"):
            call_command("reconcile_fortcom_mcf01", "--apply")

    def test_a_dry_run_reports_the_gap_without_raising(self, fortcom):
        """Nothing has been written yet, so there is nothing to fail over — the
        run is describing the position it is about to fix."""
        _bill_august(fortcom)
        _the_75k(fortcom)

        call_command("reconcile_fortcom_mcf01")
