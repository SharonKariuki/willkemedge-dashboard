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
        "overpaid": let("DON2A", "20000"),
        "credited": let("DON2B", "20000"),
        "prepaid": let("DON3A", "20000"),
        "owing": let("DON3B", "20000"),
        "clean": let("DON4A", "20000"),
        "clean_too": let("DON4B", "20000"),
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

    # DON2A — pays more than the month asks for, so August closes 250 in credit.
    overpaid = flats["overpaid"]
    _bill(overpaid, 2026, 6, 20000)
    _bill(overpaid, 2026, 7, 20000)
    _pay(overpaid, 20000, _dt.date(2026, 6, 5), (2026, 6))
    _pay(overpaid, 22500, _dt.date(2026, 8, 10), (2026, 7))

    # DON2B — the landlord credits her 2,096 in August rather than billing it.
    credited = flats["credited"]
    _bill(credited, 2026, 6, 20000)
    _bill(credited, 2026, 7, 20000)
    _pay(credited, 10000, _dt.date(2026, 7, 15), (2026, 6))
    _pay(credited, 20000, _dt.date(2026, 8, 9), (2026, 7))

    # DON3A — 21,400 in hand, and cash that landed AFTER the sheet was drawn.
    prepaid = flats["prepaid"]
    _bill(prepaid, 2026, 6, 20000)
    _bill(prepaid, 2026, 7, 20000)
    _pay(prepaid, 41400, _dt.date(2026, 6, 2), (2026, 6))
    _pay(prepaid, 21000, _dt.date(2026, 8, 26), (2026, 7))

    # DON4A / DON4B — square with the world, and never billed for August.
    clean, clean_too = flats["clean"], flats["clean_too"]
    for tenant, august in ((clean, "21200"), (clean_too, "21050")):
        _bill(tenant, 2026, 6, 20000)
        _bill(tenant, 2026, 7, 20000)
        _pay(tenant, 20000, _dt.date(2026, 6, 3), (2026, 6))
        _pay(tenant, 20000, _dt.date(2026, 7, 2), (2026, 7))
        _pay(tenant, august, _dt.date(2026, 8, 5), (2026, 8))

    return flats


#  The landlord's 21 Aug 2026 "Outstanding Balances" sheet, all eight units.
#
#  Two rows are held at what the sheet's own columns add up to rather than the
#  total it prints, because the printed total does not foot: DON2B is
#  6,150 + 20,000 - 2,096 = 24,054 against a printed 24,055, and DON3B is
#  34,445 + 20,000 + 2,623 = 57,068 against a printed 57,067. The components are
#  the figures the landlord's water and rent records support, so the roll lands
#  a shilling under the printed balance on those two rows and that is recorded
#  rather than fudged.
SHEET = {
    #  unit,     b/f,  rent,  other,   paid,  unpaid
    "DON1A": (7800, 15000, 1500, 16000, 8300),
    "DON1B": (-900, 20000, 2550, 21650, 0),
    "DON2A": (1050, 20000, 1200, 22500, -250),
    "DON2B": (6150, 20000, -2096, 20000, 4054),
    "DON3A": (-21400, 20000, 1350, 0, -50),
    "DON3B": (34445, 20000, 2623, 20000, 37068),
    "DON4A": (0, 20000, 1200, 21200, 0),
    "DON4B": (0, 20000, 1050, 21050, 0),
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


def _roll(tenant, as_of=None):
    """The rent roll. ``as_of`` reproduces it as the statement date saw it."""
    return {
        r["period"]: r
        for r in build_monthly_ledger(tenant, months=0, today=AUG_21, as_of=as_of)
    }


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

    def test_a_short_posted_charge_is_adjusted_not_overwritten(self, donholm, monkeypatch):
        """DON1A's production shape: a 900 water charge against the sheet's 1,500.

        Overwriting would discard a meter reading someone posted deliberately;
        skipping leaves the unit permanently short of the sheet. Post the
        difference as its own line — both rows survive and the month totals to
        the landlord's figure.
        """
        _stmt(monkeypatch, donholm.values(), only={"DON1A"})
        UtilityCharge.objects.create(
            tenant=donholm["misfiled"], posting_date=_dt.date(2026, 8, 1),
            period_year=2026, period_month=8, label="Water Usage", amount=D("900"),
        )

        call_command("reconcile_donholm", "--apply")

        charges = UtilityCharge.objects.filter(
            tenant=donholm["misfiled"], period_year=2026, period_month=8
        ).order_by("id")
        assert [c.amount for c in charges] == [D("900"), D("600")], (
            "the posted reading must survive and be topped up, not replaced"
        )
        assert "900" in charges[1].notes and "1500" in charges[1].notes, (
            "the adjustment must state what it reconciles"
        )

    def test_an_over_posted_charge_is_adjusted_downwards(self, donholm, monkeypatch):
        """The correction runs both ways, and never deletes the original."""
        _stmt(monkeypatch, donholm.values(), only={"DON1A"})
        UtilityCharge.objects.create(
            tenant=donholm["misfiled"], posting_date=_dt.date(2026, 8, 1),
            period_year=2026, period_month=8, label="Water Usage", amount=D("2000"),
        )

        call_command("reconcile_donholm", "--apply")

        charges = UtilityCharge.objects.filter(
            tenant=donholm["misfiled"], period_year=2026, period_month=8
        ).order_by("id")
        assert [c.amount for c in charges] == [D("2000"), D("-500")]

    def test_an_adjusted_month_still_reproduces_the_sheet(self, donholm, monkeypatch):
        """The point of adjusting rather than skipping: DON1A reconciles."""
        _stmt(monkeypatch, donholm.values(), only={"DON1A"})
        UtilityCharge.objects.create(
            tenant=donholm["misfiled"], posting_date=_dt.date(2026, 8, 1),
            period_year=2026, period_month=8, label="Water Usage", amount=D("900"),
        )

        call_command("reconcile_donholm", "--apply")

        bf, rent, other, paid, unpaid = SHEET["DON1A"]
        row = _roll(donholm["misfiled"])["8/2026"]
        assert D(row["other_charges"]) == D(other)
        assert D(row["paid"]) == D(paid)
        assert D(row["balance"]) == D(unpaid)

    def test_adjusting_is_idempotent(self, donholm, monkeypatch):
        """A second run sees the month already totalling the sheet and stops."""
        _stmt(monkeypatch, donholm.values(), only={"DON1A"})
        UtilityCharge.objects.create(
            tenant=donholm["misfiled"], posting_date=_dt.date(2026, 8, 1),
            period_year=2026, period_month=8, label="Water Usage", amount=D("900"),
        )

        call_command("reconcile_donholm", "--apply")
        call_command("reconcile_donholm", "--apply")

        assert UtilityCharge.objects.filter(tenant=donholm["misfiled"]).count() == 2


class TestReconciles:
    """The acceptance tests: the rebuilt August row must equal the sheet."""

    @pytest.mark.parametrize("key", [
        "misfiled", "credit", "overpaid", "credited",
        "prepaid", "owing", "clean", "clean_too",
    ])
    def test_august_row_reproduces_the_sheet(self, donholm, monkeypatch, key):
        _stmt(monkeypatch, donholm.values())

        call_command("reconcile_donholm", "--apply")

        tenant = donholm[key]
        bf, rent, other, paid, unpaid = SHEET[tenant.unit.label]
        # The sheet is a snapshot taken on 21 Aug, so hold the roll against it
        # as at that date. DON3A is the row that makes the distinction matter:
        # she paid 21,000 on 26 August, five days after it was drawn.
        row = _roll(tenant, as_of=AUG_21)["8/2026"]
        assert D(row["brought_forward"]) == D(bf)
        assert D(row["rent"]) == D(rent)
        assert D(row["other_charges"]) == D(other)
        assert D(row["total_due"]) == D(bf) + D(rent) + D(other)
        assert D(row["paid"]) == D(paid)
        assert D(row["balance"]) == D(unpaid)

    def test_cash_banked_after_the_sheet_shows_in_the_live_roll(self, donholm, monkeypatch):
        """The sheet is a snapshot, not a cap.

        DON3A's 21,000 landed on 26 August. It is absent from the 21 Aug
        snapshot — correctly, it had not arrived — and present in the roll the
        dashboard renders, which is the roll as of today. Reconciling to the
        sheet must not swallow cash banked after it was drawn.
        """
        _stmt(monkeypatch, donholm.values())

        call_command("reconcile_donholm", "--apply")

        prepaid = donholm["prepaid"]
        snapshot = _roll(prepaid, as_of=AUG_21)["8/2026"]
        live = _roll(prepaid)["8/2026"]
        assert D(snapshot["paid"]) == D(0), "the sheet was drawn before the cash arrived"
        assert D(live["paid"]) == D("21000"), "the later payment was lost"
        assert D(live["balance"]) == D("-21050"), "21,400 in hand plus 21,000 banked"

    @pytest.mark.parametrize("key", [
        "misfiled", "credit", "overpaid", "credited",
        "prepaid", "owing", "clean", "clean_too",
    ])
    def test_payment_history_reconciles_with_the_rent_roll(self, donholm, monkeypatch, key):
        """The two tables on the tenant page must tell the same story.

        The payment history lists receipts; the roll aggregates them by the
        month the cash arrived. They read from the same records by different
        paths, which is exactly how they drift — the roll used to key receipts
        by the FIFO settlement period, so a payment shown in the history under
        August was counted into the roll's June.
        """
        _stmt(monkeypatch, donholm.values())

        call_command("reconcile_donholm", "--apply")

        tenant = donholm[key]
        roll = _roll(tenant)
        by_month = {}
        for pay in Payment.objects.filter(tenant=tenant, voided_at__isnull=True):
            k = f"{pay.payment_date.month}/{pay.payment_date.year}"
            by_month[k] = by_month.get(k, D(0)) + pay.amount
        for period, amount in by_month.items():
            assert D(roll[period]["paid"]) == amount, (
                f"{period}: history has {amount}, roll shows {roll[period]['paid']}"
            )

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
        """The units board must say what the rebuilt roll says.

        ARREARS exactly where August closes owing, and not on the two rows
        that close in credit — DON2A by 250 and DON3A by 21,050 — even though
        both still carry an open earlier period, because cash now sits in the
        month it arrived rather than against the oldest debt.
        """
        _stmt(monkeypatch, donholm.values())

        call_command("reconcile_donholm", "--apply")

        expected = {
            "DON1A": UnitStatus.ARREARS,        # owes 8,300
            "DON1B": UnitStatus.OCCUPIED_PAID,  # closes at zero
            "DON2A": UnitStatus.OCCUPIED_PAID,  # 250 in credit
            "DON2B": UnitStatus.ARREARS,        # owes 4,054
            "DON3A": UnitStatus.OCCUPIED_PAID,  # 21,050 in credit
            "DON3B": UnitStatus.ARREARS,        # owes 37,068
            "DON4A": UnitStatus.OCCUPIED_PAID,
            "DON4B": UnitStatus.OCCUPIED_PAID,
        }
        got = {}
        for tenant in donholm.values():
            tenant.unit.refresh_from_db()
            got[tenant.unit.label] = tenant.unit.status
        assert got == expected

    def test_a_status_never_contradicts_the_roll(self, donholm, monkeypatch):
        """The invariant behind the table above, stated once.

        ARREARS on a unit whose roll closes at or below zero is the defect
        this pins; so is a unit reading paid while the roll shows debt carried
        from an earlier month.
        """
        _stmt(monkeypatch, donholm.values())

        call_command("reconcile_donholm", "--apply")

        for tenant in donholm.values():
            tenant.unit.refresh_from_db()
            closing = D(_roll(tenant)["8/2026"]["balance"])
            if tenant.unit.status == UnitStatus.ARREARS:
                assert closing > 0, (
                    f"{tenant.unit.label} reads ARREARS on a roll closing at {closing}"
                )
            else:
                assert closing <= 0, (
                    f"{tenant.unit.label} reads {tenant.unit.status} owing {closing}"
                )
