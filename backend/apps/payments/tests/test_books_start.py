"""
Restarting a tenant's books on the landlord's end-of-month balance.

A tenant with an ``OpeningBalance`` carries the sheet's figure across ``as_of``
and nothing from before it; a tenant without one keeps their whole history.
Every balance the product reports — the rent roll, the statement, aging, the
ledger — has to agree on that, so each is asserted here against one scenario:

  history  June and July rent of 9,000 raised, 4,000 paid in July, a one-off
           July charge — 18,000 + 500 - 4,000 = 14,500 owed by the old books
  sheet    the landlord says the tenant owed 3,000 at 31 August
  books    September rent 9,000; August's metered water (1,200) rides on the
           September invoice; 9,000 paid on 5 September
"""
import datetime as _dt
import io
from decimal import Decimal

import pytest
from django.core.management import call_command

from apps.buildings.models import Building, Unit, UnitStatus
from apps.payments import books
from apps.payments.models import (
    Arrears,
    OpeningBalance,
    Payment,
    PaymentSource,
    PaymentType,
    UtilityCharge,
)
from apps.payments.monthly_ledger import build_monthly_ledger, current_balance
from apps.tenants.models import Tenant, TenantStatus

AS_OF = _dt.date(2026, 8, 31)
TODAY = _dt.date(2026, 9, 20)


@pytest.fixture
def tenant(db):
    building = Building.objects.create(name="Matasia Residential", total_floors=4)
    unit = Unit.objects.create(
        building=building, label="MR999", monthly_rent=Decimal("9000"),
        status=UnitStatus.OCCUPIED_UNPAID,
    )
    return Tenant.objects.create(
        first_name="Test", last_name="Tenant", id_number="TEST-MR999",
        phone="+254700000009", unit=unit, monthly_rent=Decimal("9000"),
        deposit_paid=Decimal("0"), move_in_date=_dt.date(2026, 6, 1),
        status=TenantStatus.ACTIVE,
    )


def _bill(tenant, month, rent="9000"):
    return Arrears.objects.create(
        tenant=tenant, period_month=month, period_year=2026,
        expected_rent=Decimal(rent), amount_paid=0, balance=Decimal(rent),
    )


def _pay(tenant, day, amount, ptype=PaymentType.RENT, **kwargs):
    defaults = {"period_month": day.month, "period_year": day.year}
    defaults.update(kwargs)
    return Payment.objects.create(
        tenant=tenant, amount=Decimal(amount), payment_date=day,
        source=PaymentSource.MPESA, payment_type=ptype, **defaults,
    )


@pytest.fixture
def history(tenant):
    _bill(tenant, 6)
    _bill(tenant, 7)
    _pay(tenant, _dt.date(2026, 7, 10), "4000", period_month=6)
    UtilityCharge.objects.create(
        tenant=tenant, label="Other costs", amount=Decimal("500"),
        posting_date=_dt.date(2026, 7, 15), period_month=7, period_year=2026,
    )
    return tenant


@pytest.fixture
def restarted(history):
    tenant = history
    _bill(tenant, 9)
    UtilityCharge.objects.create(
        tenant=tenant, label="Water Usage", amount=Decimal("1200"),
        posting_date=_dt.date(2026, 8, 28), period_month=8, period_year=2026,
    )
    _pay(tenant, _dt.date(2026, 9, 5), "9000", period_month=6)
    OpeningBalance.objects.create(
        tenant=tenant, as_of=AS_OF, amount=Decimal("3000"), source="test sheet",
    )
    return tenant


class TestWithoutARestart:
    def test_full_history_still_counts(self, history):
        assert current_balance(history, today=TODAY) == Decimal("14500.00")


class TestBalances:
    def test_balance_is_the_sheet_figure_plus_activity_since(self, restarted):
        # 3,000 + 9,000 rent + 1,200 August water - 9,000 paid
        assert current_balance(restarted, today=TODAY) == Decimal("4200.00")

    def test_rent_roll_opens_on_the_sheet(self, restarted):
        rows = build_monthly_ledger(restarted, today=TODAY)
        # June and July are history: the roll starts at the opening month.
        assert (rows[0]["period_month"], rows[0]["period_year"]) == (8, 2026)
        assert rows[0]["brought_forward"] == "3000.00"
        assert rows[0]["is_opening"]
        september = rows[1]
        # August's water is billed with September's rent, so it shows there.
        assert september["other_charges"] == "1200.00"
        assert rows[-1]["balance"] == "4200.00"

    def test_statement_prints_one_brought_forward_line(self, restarted):
        from apps.payments.statement_service import _build_ledger

        lines, closing, _bf = _build_ledger(restarted, as_of=TODAY)
        text = [ln["description"] for ln in lines]
        assert "Balance brought forward - August-2026" in text
        assert not any("June" in t or "July" in t for t in text)
        assert closing == Decimal("4200.00")

    def test_aging_sums_to_the_balance(self, restarted):
        from apps.payments.aging import aging_buckets

        aged = aging_buckets([restarted], today=TODAY)[restarted.pk]
        assert aged["total"] == Decimal("4200.00")

    def test_an_opening_credit_is_credit_in_hand(self, history):
        _bill(history, 9)
        OpeningBalance.objects.create(
            tenant=history, as_of=AS_OF, amount=Decimal("-20000"), source="test sheet",
        )
        assert current_balance(history, today=TODAY) == Decimal("-11000.00")
        books.resettle(history)
        september = Arrears.objects.get(tenant=history, period_month=9)
        assert september.is_cleared and september.balance == 0
        from apps.payments.services import available_credit

        assert available_credit(history) == Decimal("11000.00")


class TestSubledger:
    def test_new_money_never_settles_a_month_before_the_books(self, restarted):
        from apps.payments.services import allocate_payment_fifo

        books.resettle(restarted)
        created = allocate_payment_fifo(
            tenant=restarted, amount=Decimal("1000"), payment_date=_dt.date(2026, 9, 25),
        )
        assert all((p.period_year, p.period_month) >= (2026, 9) for p in created)

    def test_resettle_puts_what_is_owed_on_the_newest_month(self, restarted):
        books.resettle(restarted)
        # The 9,000 paid in September went to June when it arrived; after the
        # restart the 4,200 owed sits on September, the only month in the books.
        september = Arrears.objects.get(tenant=restarted, period_month=9)
        assert september.balance == Decimal("4200.00")

    def test_billing_never_reaches_back_before_the_books(self, restarted):
        from apps.payments.tasks import first_billable_period

        assert first_billable_period(restarted, None) == (2026, 9)


class TestLedger:
    def test_receivable_ties_to_the_rent_roll(self, restarted):
        from apps.ledger.checks import _check_receivable

        result = _check_receivable(TODAY)
        assert result.ok, result.detail

    def test_undoing_the_restart_restores_the_full_history(self, restarted):
        from apps.ledger.checks import _check_receivable

        OpeningBalance.objects.filter(tenant=restarted).delete()
        # 14,500 of history + September's 9,000 rent + 1,200 water - 9,000 paid
        assert current_balance(restarted, today=TODAY) == Decimal("15700.00")
        assert _check_receivable(TODAY).ok

    def test_rebuild_keeps_it_tied(self, restarted):
        from apps.ledger.checks import _check_receivable
        from apps.ledger.rebuild import rebuild

        rebuild()
        assert _check_receivable(TODAY).ok


class TestCommand:
    def _csv(self, tmp_path, body):
        path = tmp_path / "sheet.csv"
        path.write_text("unit,opening,deposit,first_other,check_date,check_balance\n" + body)
        return str(path)

    def _run(self, path, *extra):
        out = io.StringIO()
        call_command(
            "set_opening_balances", path, "--as-of", "2026-08-31",
            "--source", "test sheet", *extra, stdout=out,
        )
        return out.getvalue()

    def test_dry_run_saves_nothing(self, history, tmp_path):
        out = self._run(self._csv(tmp_path, "MR999,3000,,,,\n"))
        assert "DRY RUN" in out
        assert not OpeningBalance.objects.exists()

    def test_apply_restarts_and_is_idempotent(self, history, tmp_path):
        path = self._csv(tmp_path, "MR999,3000,9000,700,2026-08-31,3000\n")
        self._run(path, "--apply")
        ob = OpeningBalance.objects.get(tenant=history)
        assert (ob.amount, ob.as_of, ob.books_key) == (Decimal("3000"), AS_OF, 2026 * 12 + 9)
        from apps.tenants.deposits import deposit_held_on_books

        assert deposit_held_on_books(history) == Decimal("9000.00")
        adjustment = UtilityCharge.objects.get(tenant=history, label__startswith="Other costs - sheet")
        assert adjustment.amount == Decimal("700")
        payments_before = Payment.objects.count()
        out = self._run(path, "--apply")
        assert Payment.objects.count() == payments_before
        assert "check 2026-08-31: app 3,000.00 vs sheet 3,000.00" in out

    def test_lowering_a_received_deposit_keeps_the_money_as_rent(self, history, tmp_path):
        _pay(history, _dt.date(2026, 9, 2), "12000", ptype=PaymentType.DEPOSIT, reference="ABC123")
        self._run(self._csv(tmp_path, "MR999,0,9000,,,\n"), "--apply")
        rent = Payment.objects.get(tenant=history, payment_type=PaymentType.RENT, reference="ABC123")
        assert rent.amount == Decimal("3000")

    def test_lowering_a_booked_deposit_invents_no_rent(self, history, tmp_path):
        _pay(
            history, _dt.date(2026, 9, 15), "12000", ptype=PaymentType.DEPOSIT,
            notes="Deposit on the tenant card, booked by sync_deposit_bookings.",
        )
        self._run(self._csv(tmp_path, "MR999,0,9000,,,\n"), "--apply")
        assert not Payment.objects.filter(
            tenant=history, payment_type=PaymentType.RENT, payment_date=_dt.date(2026, 9, 15)
        ).exists()

    def test_an_unknown_unit_blocks_apply(self, history, tmp_path):
        from django.core.management.base import CommandError

        with pytest.raises(CommandError):
            self._run(self._csv(tmp_path, "MR999,0,,,,\nNOPE1,0,,,,\n"), "--apply")
        assert not OpeningBalance.objects.exists()

    def test_undo(self, history, tmp_path):
        path = self._csv(tmp_path, "MR999,3000,,,,\n")
        self._run(path, "--apply")
        self._run(path, "--undo", "--apply")
        assert not OpeningBalance.objects.exists()
