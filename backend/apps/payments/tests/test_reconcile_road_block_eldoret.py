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
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

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


@pytest.mark.django_db
class TestRowsThatCannotResolve:
    """A unit let to somebody the statement never mentions blocks its own row.

    This is what production hit: RB109 and RB401 were on file under tenants
    the sheet does not name, and pre-flight aborted the entire command under
    --apply, so every other row on the property — Sarah & Hussein Hamisi's
    included — stayed unreconciled through several production runs. Those two
    units are now settled by ``RELET``, so the general case is exercised on
    units the realignment steps say nothing about.
    """

    @staticmethod
    def _occupy(label, first, last):
        """Re-let ``label`` to someone the statement does not name."""
        unit = Unit.objects.get(label=label)
        Tenant.objects.filter(unit=unit).update(status=TenantStatus.MOVED_OUT)
        return Tenant.objects.create(
            first_name=first, last_name=last, id_number=f"ID-INTRUDER-{label}",
            phone="+254700000001", unit=unit, monthly_rent=unit.monthly_rent,
            deposit_paid=D(0), move_in_date="2026-06-16", status=TenantStatus.ACTIVE,
        )

    def test_an_unresolvable_row_no_longer_blocks_the_property(self, road_block):
        self._occupy("RB103", "Daniel", "Otieno")
        self._occupy("RB110", "Sheila", "Namusonge")

        call_command("reconcile_road_block_eldoret", "--apply", verbosity=0)

        august = _row(_tenant("RB101"))
        assert _money(august["brought_forward"]) == D("0.00")
        assert _money(august["rent"]) == D("8300.00")
        assert _money(august["balance"]) == D("0.00")

    def test_the_rest_of_the_sheet_still_reproduces(self, road_block):
        self._occupy("RB103", "Daniel", "Otieno")
        self._occupy("RB110", "Sheila", "Namusonge")
        blocked = {"RB103", "RB110"}

        call_command("reconcile_road_block_eldoret", "--apply", verbosity=0)

        wrong = []
        for label, name, bf, rent, other, paid, _total, _balance in cmd.STATEMENT:
            if label in blocked:
                continue
            row = _row(_tenant(label))
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

    def test_the_occupier_of_a_blocked_unit_is_left_alone(self, road_block):
        """No figure from the sheet may land on a tenant it does not name."""
        intruder = self._occupy("RB103", "Daniel", "Otieno")

        call_command("reconcile_road_block_eldoret", "--apply", verbosity=0)

        assert not Arrears.objects.filter(tenant=intruder).exists()
        assert not Payment.objects.filter(tenant=intruder).exists()

    def test_the_blocked_rows_are_reported_at_the_end(self, road_block):
        self._occupy("RB103", "Daniel", "Otieno")
        self._occupy("RB110", "Sheila", "Namusonge")
        out = StringIO()

        call_command("reconcile_road_block_eldoret", "--apply", stdout=out)

        tail = out.getvalue().split("NOT RECONCILED")[-1]
        assert "RB103" in tail and "Daniel Otieno" in tail
        assert "RB110" in tail and "Sheila Namusonge" in tail

    def test_a_property_that_resolves_nowhere_still_aborts(self, road_block, monkeypatch):
        """Wrong building or wrong database — that is not a per-row question."""
        # Steps 0b2 and 0c would otherwise seat the tenants the statement names
        # but the database lacks, leaving those rows resolving on their own.
        monkeypatch.setattr(cmd, "NEW_TENANTS", [])
        monkeypatch.setattr(cmd, "RELET", [])
        Tenant.objects.filter(unit__building=road_block).update(
            status=TenantStatus.MOVED_OUT
        )

        with pytest.raises(CommandError, match="not one statement row resolves"):
            call_command("reconcile_road_block_eldoret", "--apply", verbosity=0)


@pytest.mark.django_db
class TestProductionSubledgerShape:
    """RB101 exactly as the live database holds her, read 31 Aug 2026.

        ARR 6  8300.00 paid 8300.00  balance 0.00
        ARR 7  8300.00 paid 8300.00  balance 0.00     <- August's cash, FIFO'd
        (no August arrears row at all)

    The subledger settled July with the receipt that arrived in August, while
    the cash-basis roll reports that receipt in August — so the roll shows July
    unpaid and August opening at 8,300 against a rent of nil, which is what the
    landlord queried. The general fixture raises an August arrears row instead,
    so this shape is pinned separately.
    """

    @pytest.fixture
    def rb101_as_in_production(self, road_block):
        from apps.payments.services import process_payment

        tenant = _tenant("RB101")
        # Transaction.payment is PROTECTed, so the postings go before the cash.
        Transaction.objects.filter(tenant=tenant).delete()
        Payment.objects.filter(tenant=tenant).delete()
        Arrears.objects.filter(tenant=tenant).delete()
        for month in (6, 7):
            Arrears.objects.create(
                tenant=tenant, period_year=2026, period_month=month,
                expected_rent=D("8300"), expected_vat=D(0), amount_paid=D(0),
                balance=D("8300"), is_cleared=False,
            )
        process_payment(
            tenant=tenant, amount=D("8300"), payment_date=_dt.date(2026, 6, 20),
            period_month=6, period_year=2026, source="mpesa",
            reference="PROD-JUN-RB101", idempotency_key="PROD-JUN-RB101",
        )
        # Received in August, allocated by the subledger against July.
        process_payment(
            tenant=tenant, amount=D("8300"), payment_date=_dt.date(2026, 8, 12),
            period_month=7, period_year=2026, source="bank",
            reference="PROD-AUG-RB101", idempotency_key="PROD-AUG-RB101",
        )
        return tenant

    def test_the_fixture_reproduces_what_the_landlord_queried(self, rb101_as_in_production):
        assert not Arrears.objects.filter(
            tenant=rb101_as_in_production, period_year=2026, period_month=8
        ).exists()
        august = _row(rb101_as_in_production)
        assert _money(august["brought_forward"]) == D("8300.00")
        assert _money(august["rent"]) == D("0.00")

    def test_the_command_puts_her_row_right(self, rb101_as_in_production):
        call_command("reconcile_road_block_eldoret", "--apply", verbosity=0)

        july = _row(rb101_as_in_production, month=7)
        august = _row(rb101_as_in_production)
        assert july["is_opening"] and _money(july["balance"]) == D("0.00")
        assert _money(august["brought_forward"]) == D("0.00")
        assert _money(august["rent"]) == D("8300.00")
        assert _money(august["paid"]) == D("8300.00")
        assert _money(august["balance"]) == D("0.00")

    def test_her_august_cash_is_not_banked_twice(self, rb101_as_in_production):
        call_command("reconcile_road_block_eldoret", "--apply", verbosity=0)

        received = Payment.objects.filter(
            tenant=rb101_as_in_production, voided_at__isnull=True,
            payment_date__year=2026, payment_date__month=8,
        )
        assert sum(p.amount for p in received) == D("8300.00")


@pytest.mark.django_db
class TestReLetting:
    """RB109 and RB401 are on file under tenants the sheet never mentions.

    The landlord settled it on 31 Aug 2026: the statement is right, the
    database is stale. Both units go to the tenant the sheet names — moved
    across if that tenant is already on file, created from the sheet if not —
    and the sitting tenant is moved out rather than deleted.
    """

    @staticmethod
    def _sit(label, first, last):
        """Put a stale tenant on ``label``, keeping the history it carries.

        Production's stale occupants have their own arrears and receipts, so
        the fixture's tenant is renamed rather than replaced — deleting one
        would take a history the real thing still has.
        """
        sitting = _tenant(label)
        sitting.first_name, sitting.last_name = first, last
        sitting.save(update_fields=["first_name", "last_name"])
        return sitting

    def test_the_statement_tenant_is_created_when_not_on_file(self, road_block):
        stale = self._sit("RB109", "Daniel", "Otieno")

        call_command("reconcile_road_block_eldoret", "--apply", verbosity=0)

        assert _tenant("RB109").full_name == "Diana Ochola"
        stale.refresh_from_db()
        assert stale.status == TenantStatus.MOVED_OUT

    def test_a_re_let_row_then_reconciles_to_the_sheet(self, road_block):
        self._sit("RB109", "Daniel", "Otieno")

        call_command("reconcile_road_block_eldoret", "--apply", verbosity=0)

        row = _row(_tenant("RB109"))  # sheet: b/f 207, rent 5,000, paid 0
        assert _money(row["brought_forward"]) == D("207.00")
        assert _money(row["rent"]) == D("5000.00")
        assert _money(row["balance"]) == D("5207.00")

    def test_an_existing_record_is_moved_not_duplicated(self, road_block):
        """Moving keeps the tenant's own arrears history; a copy would split it."""
        self._sit("RB109", "Daniel", "Otieno")
        spare = Unit.objects.create(
            building=Unit.objects.get(label="RB109").building, label="RB998",
            monthly_rent=D("5000"), classification=UnitClassification.RESIDENTIAL,
            status=UnitStatus.OCCUPIED_UNPAID,
        )
        existing = Tenant.objects.create(
            first_name="Diana", last_name="Ochola", id_number="ID-DIANA-REAL",
            phone="+254102574415", unit=spare, monthly_rent=D("5000"),
            deposit_paid=D(0), move_in_date="2026-06-16", status=TenantStatus.ACTIVE,
        )

        call_command("reconcile_road_block_eldoret", "--apply", verbosity=0)

        assert Tenant.objects.filter(first_name="Diana", last_name="Ochola").count() == 1
        existing.refresh_from_db()
        assert existing.unit.label == "RB109"

    def test_a_tenant_with_no_phone_on_the_sheet_is_not_invented(self, road_block):
        """RB401's incoming tenant has no number on the statement image.

        Nobody is evicted for a replacement that cannot be seated: the unit
        would be left with no tenant at all, which is worse than the stale
        name it has now. The row is reported under NOT RECONCILED instead.
        """
        sheila = self._sit("RB401", "Sheila", "Khaemba Namusonge")
        out = StringIO()

        call_command("reconcile_road_block_eldoret", "--apply", stdout=out)

        assert not Tenant.objects.filter(first_name="Noah", last_name="Omollo").exists()
        sheila.refresh_from_db()
        assert sheila.status == TenantStatus.ACTIVE
        assert "no phone number" in out.getvalue()
        assert "RB401" in out.getvalue().split("NOT RECONCILED")[-1]

    def test_somebody_the_sheet_houses_elsewhere_is_never_evicted(self, road_block):
        """A re-let must not throw out a tenant the statement accounts for."""
        unit = Unit.objects.get(label="RB109")
        Tenant.objects.filter(unit=unit).update(status=TenantStatus.MOVED_OUT)
        tabitha = _tenant("RB103")
        tabitha.unit = unit
        tabitha.save(update_fields=["unit"])

        call_command("reconcile_road_block_eldoret", "--apply", verbosity=0)

        tabitha.refresh_from_db()
        assert tabitha.status == TenantStatus.ACTIVE
        assert tabitha.unit.label == "RB109"

    def test_re_letting_is_idempotent(self, road_block):
        self._sit("RB109", "Daniel", "Otieno")
        call_command("reconcile_road_block_eldoret", "--apply", verbosity=0)

        out = StringIO()
        call_command("reconcile_road_block_eldoret", "--apply", stdout=out)

        assert "already let to Diana Ochola" in out.getvalue()
        assert Tenant.objects.filter(first_name="Diana", last_name="Ochola").count() == 1
