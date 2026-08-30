"""
Tests for the Donholm Nairobi statement reconciliation.

The acceptance tests are the last group: after the command runs, the monthly
rent roll must reproduce the landlord's 21-08-2026 rows exactly. Three shapes
cover the property between them —

  * DON1A, the row the owner raised: every shilling of her cash arrived in
    August but the FIFO splitter filed it under June and July, so her August row
    showed no payment at all and her arrears read 14,000 against a sheet saying
    7,800.
  * DON1B, a tenant in credit: the B/Forward is negative and has to survive a
    model that cannot store a negative balance.
  * DON3B, the largest debt on the sheet, with no August row raised at all.

Everything above them pins the pieces that get there.
"""
import datetime as _dt
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.accounts.models import FinancialAuditLog
from apps.buildings.models import Building, Unit, UnitClassification, UnitStatus
from apps.payments.management.commands import reconcile_donholm as cmd
from apps.payments.models import Arrears, Payment, UtilityCharge
from apps.payments.monthly_ledger import OPENING_MARKER, build_monthly_ledger
from apps.tenants.models import Tenant, TenantStatus

D = Decimal
AUG_21 = _dt.date(2026, 8, 21)


@pytest.fixture
def flats(db):
    """Donholm as production holds it: a corrupted cutover row and misfiled cash."""
    building = Building.objects.create(name="Donholm Nairobi", code="DON", total_floors=4)

    def let(label, rent):
        unit = Unit.objects.create(
            building=building, label=label, monthly_rent=D(rent),
            classification=UnitClassification.RESIDENTIAL,
            status=UnitStatus.OCCUPIED_UNPAID,
        )
        return Tenant.objects.create(
            first_name=label, last_name="Tenant", id_number=f"T-{label}",
            phone="+254700000004", unit=unit, monthly_rent=D(rent),
            deposit_paid=D(0), move_in_date="2026-06-16", status=TenantStatus.ACTIVE,
        )

    return {
        "misfiled": let("DON1A", "15000"),
        "credit": let("DON1B", "20000"),
        "owing": let("DON3B", "20000"),
    }


def _bill(tenant, year, month, expected):
    """A raised period, as the corrupted cutover left it."""
    return Arrears.objects.create(
        tenant=tenant, period_year=year, period_month=month,
        expected_rent=D(expected), expected_vat=D(0), amount_paid=D(0),
        balance=D(expected), is_cleared=False,
    )


def _pay(tenant, amount, on, period):
    """Cash, allocated to the period FIFO chose rather than the month it arrived."""
    from apps.payments.services import process_payment

    year, month = period
    return process_payment(
        tenant=tenant, amount=D(amount), payment_date=on,
        period_month=month, period_year=year, source="mpesa",
        reference=f"REF-{tenant.pk}-{on}-{amount}",
        idempotency_key=f"KEY-{tenant.pk}-{on}-{amount}",
    )


@pytest.fixture
def donholm(flats):
    """Wire up the three tenancies with the exact production history."""
    misfiled, credit, owing = flats["misfiled"], flats["credit"], flats["owing"]

    # DON1A — cutover 7,450 overwritten to a month's rent; both payments landed
    # on 3 Aug but were split back onto June and July. No August row at all.
    _bill(misfiled, 2026, 6, 15000)
    _bill(misfiled, 2026, 7, 15000)
    _pay(misfiled, 7450, _dt.date(2026, 8, 3), (2026, 6))
    _pay(misfiled, 8550, _dt.date(2026, 8, 3), (2026, 7))

    # DON1B — genuinely overpaid in June, then paid again in August.
    _bill(credit, 2026, 6, 20000)
    _bill(credit, 2026, 7, 20000)
    _bill(credit, 2026, 8, 20000)
    _pay(credit, 22700, _dt.date(2026, 6, 5), (2026, 6))
    _pay(credit, 20000, _dt.date(2026, 8, 7), (2026, 7))
    _pay(credit, 1650, _dt.date(2026, 8, 7), (2026, 8))

    # DON3B — 51,900 brought forward, overwritten to 20,000. No August row.
    _bill(owing, 2026, 6, 20000)
    _bill(owing, 2026, 7, 20000)
    _pay(owing, 10000, _dt.date(2026, 6, 10), (2026, 6))
    _pay(owing, 10000, _dt.date(2026, 7, 30), (2026, 6))
    _pay(owing, 20000, _dt.date(2026, 8, 12), (2026, 7))

    return flats


SHEET = {
    #  unit,  b/f, rent, other, paid, unpaid
    "DON1A": (7800, 15000, 1500, 16000, 8300),
    "DON1B": (-900, 20000, 2550, 21650, 0),
    "DON3B": (34445, 20000, 2623, 20000, 37068),
}


def _stmt(monkeypatch, tenants, only=None):
    rows = []
    for tenant in tenants:
        label = tenant.unit.label
        if only and label not in only:
            continue
        bf, rent, other, paid, unpaid = SHEET[label]
        rows.append((label, tenant.pk, D(bf), D(rent), D(other), D(paid), D(unpaid)))
    monkeypatch.setattr(cmd, "STATEMENT", rows)
    return rows


def _arrears(tenant, year, month):
    return Arrears.objects.filter(
        tenant=tenant, period_year=year, period_month=month
    ).first()


def _roll(tenant):
    return {r["period"]: r for r in build_monthly_ledger(tenant, months=0, today=AUG_21)}


class TestPreflight:
    def test_aborts_when_the_id_is_on_another_unit(self, donholm, monkeypatch):
        rows = _stmt(monkeypatch, donholm.values(), only={"DON1A"})
        monkeypatch.setattr(cmd, "STATEMENT", [("DON9Z", *rows[0][1:])])

        with pytest.raises(CommandError, match="Pre-flight failed"):
            call_command("reconcile_donholm", "--apply")

    def test_writes_nothing_when_preflight_fails(self, donholm, monkeypatch):
        rows = _stmt(monkeypatch, donholm.values())
        monkeypatch.setattr(cmd, "STATEMENT", [rows[0], ("DON9Z", *rows[1][1:])])

        with pytest.raises(CommandError):
            call_command("reconcile_donholm", "--apply")

        july = _arrears(donholm["misfiled"], 2026, 7)
        assert july.expected_rent == D("15000"), "a valid row was restated despite the abort"

    def test_a_missing_tenant_is_skipped_not_fatal(self, donholm, monkeypatch):
        """An absent id may simply be a database the row does not apply to."""
        rows = _stmt(monkeypatch, donholm.values(), only={"DON1A"})
        monkeypatch.setattr(cmd, "STATEMENT", [("DON1A", 9_999_999, *rows[0][2:])])

        call_command("reconcile_donholm", "--apply")  # does not raise


class TestDryRun:
    def test_writes_nothing_without_apply(self, donholm, monkeypatch):
        _stmt(monkeypatch, donholm.values())

        call_command("reconcile_donholm")

        misfiled = donholm["misfiled"]
        assert _arrears(misfiled, 2026, 7).expected_rent == D("15000")
        assert _arrears(misfiled, 2026, 8) is None
        assert not UtilityCharge.objects.exists()
        assert Payment.objects.filter(
            tenant=misfiled, period_month=6, period_year=2026
        ).exists(), "August cash was re-pointed during a dry run"


class TestAugustCash:
    def test_august_dated_cash_moves_to_the_august_period(self, donholm, monkeypatch):
        _stmt(monkeypatch, donholm.values(), only={"DON1A"})

        call_command("reconcile_donholm", "--apply")

        misfiled = donholm["misfiled"]
        august = Payment.objects.filter(
            tenant=misfiled, period_year=2026, period_month=8, voided_at__isnull=True
        )
        assert sum(p.amount for p in august) == D("16000")

    def test_the_cash_itself_is_untouched(self, donholm, monkeypatch):
        """Only the period allocation moves — never the amount, date or tenant."""
        _stmt(monkeypatch, donholm.values(), only={"DON1A"})
        before = sorted(
            Payment.objects.filter(tenant=donholm["misfiled"]).values_list(
                "amount", "payment_date", "tenant_id"
            )
        )

        call_command("reconcile_donholm", "--apply")

        after = sorted(
            Payment.objects.filter(tenant=donholm["misfiled"]).values_list(
                "amount", "payment_date", "tenant_id"
            )
        )
        assert after == before
        assert not Payment.objects.filter(
            tenant=donholm["misfiled"], voided_at__isnull=False
        ).exists(), "cash was voided rather than re-allocated"

    def test_allocation_repairs_are_audited(self, donholm, monkeypatch):
        _stmt(monkeypatch, donholm.values(), only={"DON1A"})

        call_command("reconcile_donholm", "--apply")

        logs = FinancialAuditLog.objects.filter(action="payment.reallocate")
        assert logs.count() == 2
        assert all(log.old_values["payment_date"] == "2026-08-03" for log in logs)
        assert all(log.new_values == {"period_month": 8, "period_year": 2026} for log in logs)

    def test_july_dated_cash_stays_put(self, donholm, monkeypatch):
        """DON3B's 30 July payment is not August cash and must not move to August."""
        _stmt(monkeypatch, donholm.values(), only={"DON3B"})

        call_command("reconcile_donholm", "--apply")

        august = Payment.objects.filter(
            tenant=donholm["owing"], period_year=2026, period_month=8
        )
        assert sum(p.amount for p in august) == D("20000")


class TestOpeningPosition:
    def test_july_closes_at_the_sheets_brought_forward(self, donholm, monkeypatch):
        _stmt(monkeypatch, donholm.values(), only={"DON3B"})

        call_command("reconcile_donholm", "--apply")

        july = _arrears(donholm["owing"], 2026, 7)
        # 34,445 brought forward + the 20,000 of pre-August cash it absorbs.
        assert july.expected_rent == D("54445")
        assert july.amount_paid == D("20000")
        assert july.balance == D("34445")

    def test_the_opening_row_is_marked_as_brought_forward(self, donholm, monkeypatch):
        """Otherwise the roll reports it as a month billed at that figure."""
        _stmt(monkeypatch, donholm.values(), only={"DON3B"})

        call_command("reconcile_donholm", "--apply")

        july = _arrears(donholm["owing"], 2026, 7)
        assert OPENING_MARKER in july.waive_notes
        assert _roll(donholm["owing"])["7/2026"]["is_opening"] is True

    def test_the_corrupted_june_row_is_zeroed_not_deleted(self, donholm, monkeypatch):
        _stmt(monkeypatch, donholm.values(), only={"DON3B"})

        call_command("reconcile_donholm", "--apply")

        june = _arrears(donholm["owing"], 2026, 6)
        assert june is not None, "the cutover audit trail was deleted"
        assert june.expected_rent == D("0")
        assert june.balance == D("0")

    def test_a_credit_brought_forward_survives(self, donholm, monkeypatch):
        """Arrears cannot store a negative balance; the roll-forward must carry it."""
        _stmt(monkeypatch, donholm.values(), only={"DON1B"})

        call_command("reconcile_donholm", "--apply")

        july = _arrears(donholm["credit"], 2026, 7)
        assert july.expected_rent == D("21800")  # -900 b/f + 22,700 carried
        assert july.balance == D("0")
        assert _roll(donholm["credit"])["7/2026"]["balance"] == "-900.00"


class TestAugustCharges:
    def test_a_missing_august_row_is_raised(self, donholm, monkeypatch):
        _stmt(monkeypatch, donholm.values(), only={"DON1A"})

        call_command("reconcile_donholm", "--apply")

        august = _arrears(donholm["misfiled"], 2026, 8)
        assert august.expected_rent == D("15000")
        assert august.expected_vat == D("0"), "Donholm is residential — no VAT"

    def test_other_charges_are_posted(self, donholm, monkeypatch):
        _stmt(monkeypatch, donholm.values(), only={"DON1A"})

        call_command("reconcile_donholm", "--apply")

        charge = UtilityCharge.objects.get(tenant=donholm["misfiled"])
        assert charge.amount == D("1500")
        assert (charge.period_year, charge.period_month) == (2026, 8)

    def test_existing_other_charges_are_left_for_review(self, donholm, monkeypatch):
        """Overwriting would silently discard a figure someone posted deliberately."""
        _stmt(monkeypatch, donholm.values(), only={"DON1A"})
        UtilityCharge.objects.create(
            tenant=donholm["misfiled"], posting_date=_dt.date(2026, 8, 1),
            period_year=2026, period_month=8, label="Water Usage", amount=D("999"),
        )

        call_command("reconcile_donholm", "--apply")

        amounts = list(
            UtilityCharge.objects.filter(tenant=donholm["misfiled"]).values_list(
                "amount", flat=True
            )
        )
        assert amounts == [D("999")]


class TestReconciles:
    """The acceptance tests: the rebuilt August row must equal the sheet."""

    @pytest.mark.parametrize("key", ["misfiled", "credit", "owing"])
    def test_august_row_reproduces_the_sheet(self, donholm, monkeypatch, key):
        _stmt(monkeypatch, donholm.values())

        call_command("reconcile_donholm", "--apply")

        tenant = donholm[key]
        bf, rent, other, paid, unpaid = SHEET[tenant.unit.label]
        row = _roll(tenant)["8/2026"]
        assert D(row["brought_forward"]) == D(bf)
        assert D(row["rent"]) == D(rent)
        assert D(row["other_charges"]) == D(other)
        assert D(row["total_due"]) == D(bf) + D(rent) + D(other)
        assert D(row["paid"]) == D(paid)
        assert D(row["balance"]) == D(unpaid)

    def test_running_twice_changes_nothing(self, donholm, monkeypatch):
        _stmt(monkeypatch, donholm.values())
        call_command("reconcile_donholm", "--apply")
        before = {
            key: _roll(tenant)["8/2026"] for key, tenant in donholm.items()
        }
        payments = Payment.objects.count()

        call_command("reconcile_donholm", "--apply")

        assert {key: _roll(t)["8/2026"] for key, t in donholm.items()} == before
        assert Payment.objects.count() == payments
        assert UtilityCharge.objects.count() == len(donholm)

    def test_unit_statuses_follow_the_repaired_arrears_state(self, donholm, monkeypatch):
        _stmt(monkeypatch, donholm.values())

        call_command("reconcile_donholm", "--apply")

        misfiled = donholm["misfiled"].unit
        credit = donholm["credit"].unit
        owing = donholm["owing"].unit
        misfiled.refresh_from_db()
        credit.refresh_from_db()
        owing.refresh_from_db()

        assert misfiled.status == UnitStatus.ARREARS
        assert credit.status == UnitStatus.OCCUPIED_PAID
        assert owing.status == UnitStatus.ARREARS
