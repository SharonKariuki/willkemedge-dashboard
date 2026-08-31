"""
Tests for the Road Block Eldoret statement reconciliation.

The fixture is the shape production is actually in, which is not the shape the
local database was in when the command was written: June and July raised as
ordinary billed months, no August billing at all, and August cash already
banked by the Co-op feed. Two things went wrong against that shape and both
are pinned here.

  * Sarah & Hussein Hamisi (RB101) settled June in full and owe nothing
    forward, yet her August row opened at 8,300 arrears against a rent of nil.
    July was being rewritten to *hold* the statement's B/F rather than to
    *close* on it, so July's own 8,300 charge sailed straight into August.
  * Her 8,300 August payment was already on the account. Posting the
    statement's "Payment made" outright would have banked it twice.

The acceptance test is the last one: after the command runs, every row of the
rent roll must reproduce the landlord's 21-08-2026 sheet.
"""
import datetime as _dt
from decimal import Decimal

import pytest
from django.core.management import call_command

from apps.buildings.models import Building, Unit, UnitClassification, UnitStatus
from apps.payments.management.commands import reconcile_road_block_eldoret as cmd
from apps.payments.models import Arrears, Payment, PaymentType, Transaction
from apps.payments.monthly_ledger import build_monthly_ledger
from apps.tenants.models import Tenant, TenantStatus

D = Decimal
AUG_31 = _dt.date(2026, 8, 31)


def _money(value):
    return Decimal(str(value)).quantize(Decimal("0.01"))


def _row(tenant, year=2026, month=8):
    rows = build_monthly_ledger(tenant, months=0, today=AUG_31)
    return next(
        (r for r in rows if (r["period_year"], r["period_month"]) == (year, month)), None
    )


def _tenant(label):
    return Tenant.objects.filter(
        unit__label=label, status=TenantStatus.ACTIVE
    ).select_related("unit__building").first()


@pytest.fixture
def road_block(db):
    """Road Block as production holds it, built from the statement itself.

    Every unit on the sheet is let to the tenant the sheet names, so the
    command's tenant-realignment steps (which address production rows by
    primary key) find nothing to do and the financial steps run clean.
    """
    building = Building.objects.create(
        name="Wilkem Edge Apartments - Road Block Eldoret", code="RB", total_floors=5
    )
    for label in cmd.VACANT_UNITS:
        Unit.objects.create(
            building=building, label=label, monthly_rent=D(0),
            classification=UnitClassification.RESIDENTIAL, status=UnitStatus.VACANT,
        )

    from apps.payments.services import process_payment

    for label, name, _bf, rent, _other, paid, _total, _balance in cmd.STATEMENT:
        unit = Unit.objects.create(
            building=building, label=label, monthly_rent=rent,
            classification=UnitClassification.RESIDENTIAL,
            status=UnitStatus.OCCUPIED_UNPAID,
        )
        first, _, last = name.partition(" ")
        tenant = Tenant.objects.create(
            first_name=first, last_name=last, id_number=f"ID-{label}",
            phone="+254700000000", unit=unit, monthly_rent=rent,
            deposit_paid=D(0), move_in_date="2026-06-16", status=TenantStatus.ACTIVE,
        )
        # June and July raised as ordinary months; June settled, July left
        # unpaid. August was never billed — the monthly task has not run — but
        # the cash the sheet reports is already banked.
        for month in (6, 7):
            Arrears.objects.create(
                tenant=tenant, period_year=2026, period_month=month,
                expected_rent=rent, expected_vat=D(0), amount_paid=D(0),
                balance=rent, is_cleared=False,
            )
        process_payment(
            tenant=tenant, amount=rent, payment_date=_dt.date(2026, 6, 20),
            period_month=6, period_year=2026, source="mpesa",
            reference=f"JUN-{label}", idempotency_key=f"JUN-{label}",
        )
        if paid:
            process_payment(
                tenant=tenant, amount=paid, payment_date=_dt.date(2026, 8, 12),
                period_month=8, period_year=2026, source="bank",
                reference=f"AUG-{label}", idempotency_key=f"AUG-{label}",
            )
    return building


@pytest.mark.django_db
class TestAugustCash:
    def test_cash_already_banked_is_not_posted_twice(self, road_block):
        """The owner's row: 8,300 in, 8,300 on the sheet, 8,300 on the account."""
        call_command("reconcile_road_block_eldoret", "--apply", verbosity=0)

        sarah = _tenant("RB101")
        august = Payment.objects.filter(
            tenant=sarah, voided_at__isnull=True,
            payment_date__year=2026, payment_date__month=8,
        ).exclude(payment_type=PaymentType.DEPOSIT)
        assert august.count() == 1
        assert _money(sum(p.amount for p in august)) == D("8300.00")

    def test_only_the_shortfall_is_posted(self, road_block):
        """Half the month banked → the command tops up the difference, no more."""
        beryl = _tenant("RB201")  # sheet: 1,000 received against 9,000 rent
        banked = Payment.objects.filter(tenant=beryl, payment_date__month=8)
        Transaction.objects.filter(payment__in=banked).delete()
        banked.delete()
        from apps.payments.services import process_payment

        process_payment(
            tenant=beryl, amount=D("400"), payment_date=_dt.date(2026, 8, 9),
            period_month=8, period_year=2026, source="mpesa",
            reference="PART-RB201", idempotency_key="PART-RB201",
        )

        call_command("reconcile_road_block_eldoret", "--apply", verbosity=0)

        assert _money(_row(beryl)["paid"]) == D("1000.00")

    def test_cash_above_the_sheet_is_left_alone(self, road_block):
        """A receipt is real money. The command reports it, it does not delete it."""
        from apps.payments.services import process_payment

        tabitha = _tenant("RB103")  # sheet: 9,000
        process_payment(
            tenant=tabitha, amount=D("2000"), payment_date=_dt.date(2026, 8, 27),
            period_month=8, period_year=2026, source="mpesa",
            reference="EXTRA-RB103", idempotency_key="EXTRA-RB103",
        )

        call_command("reconcile_road_block_eldoret", "--apply", verbosity=0)

        assert _money(_row(tabitha)["paid"]) == D("11000.00")


@pytest.mark.django_db
class TestJulyOpening:
    def test_july_closes_on_the_statement_b_f(self, road_block):
        """July's own unpaid charge must not be carried into August."""
        call_command("reconcile_road_block_eldoret", "--apply", verbosity=0)

        sarah = _tenant("RB101")
        july, august = _row(sarah, month=7), _row(sarah)
        assert _money(july["balance"]) == D("0.00")
        assert _money(august["brought_forward"]) == D("0.00")
        assert _money(august["rent"]) == D("8300.00")

    def test_a_credit_brought_forward_survives(self, road_block):
        """Mariane Mukabwa is 2,300 ahead on the sheet."""
        call_command("reconcile_road_block_eldoret", "--apply", verbosity=0)

        assert _money(_row(_tenant("RB203"))["brought_forward"]) == D("-2300.00")

    def test_no_cash_is_invented_to_open_a_debt(self, road_block):
        """Viola Tuwei owes 29,500 forward and paid nothing in August."""
        call_command("reconcile_road_block_eldoret", "--apply", verbosity=0)

        viola = _tenant("RB308")
        assert _money(_row(viola)["brought_forward"]) == D("29500.00")
        assert _money(_row(viola)["paid"]) == D("0.00")


@pytest.mark.django_db
class TestIdempotence:
    def test_a_second_run_changes_nothing(self, road_block):
        call_command("reconcile_road_block_eldoret", "--apply", verbosity=0)
        before = {
            label: dict(_row(_tenant(label))) for label, *_ in cmd.STATEMENT
        }
        payments = Payment.objects.count()

        call_command("reconcile_road_block_eldoret", "--apply", verbosity=0)

        assert Payment.objects.count() == payments
        for label, *_ in cmd.STATEMENT:
            assert dict(_row(_tenant(label))) == before[label], label


@pytest.mark.django_db
class TestRentRollMatchesTheSheet:
    def test_every_row_reproduces_the_landlord_statement(self, road_block):
        call_command("reconcile_road_block_eldoret", "--apply", verbosity=0)

        wrong = []
        for label, name, bf, rent, other, paid, _total, _balance in cmd.STATEMENT:
            row = _row(_tenant(label))
            # The sheet's own "Balance Pending" column leaves Others Charges out
            # of the total (see the notes the command prints), so the balance is
            # held against the columns it does foot from.
            expected = {
                "brought_forward": _money(bf),
                "rent": _money(rent),
                "other_charges": _money(other),
                "paid": _money(paid),
                "balance": _money(bf + rent + other - paid),
            }
            got = {k: _money(row[k]) for k in expected}
            if got != expected:
                wrong.append(f"{label} {name}: {got} != {expected}")
        assert not wrong, "\n".join(wrong)


@pytest.mark.django_db
class TestStatementPdf:
    def test_summary_reads_like_the_sheet(self, road_block):
        """Arrears B/F 0, Month Rent 8,300 — the row the owner queried."""
        from apps.payments.statement_service import build_statement

        call_command("reconcile_road_block_eldoret", "--apply", verbosity=0)

        st = build_statement(_tenant("RB101"), statement_date=AUG_31)
        assert st["arrears_bf"] == "0.00"
        assert st["month_rent"] == "8,300.00"
        assert st["rent_plus_arrears"] == "8,300.00"
        assert st["unpaid_balance"] == "0.00"

    def test_a_nil_opening_position_is_not_printed(self, road_block):
        from apps.payments.statement_service import build_statement

        call_command("reconcile_road_block_eldoret", "--apply", verbosity=0)

        st = build_statement(_tenant("RB101"), statement_date=AUG_31)
        assert not [r for r in st["rows"] if not r["invoice_amount"] and not r["payment"]]
        assert not [r for r in st["rows"] if "brought forward" in r["description"].lower()]

    def test_a_real_opening_position_is_still_printed(self, road_block):
        from apps.payments.statement_service import build_statement

        call_command("reconcile_road_block_eldoret", "--apply", verbosity=0)

        st = build_statement(_tenant("RB308"), statement_date=AUG_31)
        brought = [r for r in st["rows"] if "brought forward" in r["description"].lower()]
        assert [r["invoice_amount"] for r in brought] == ["29,500.00"]
