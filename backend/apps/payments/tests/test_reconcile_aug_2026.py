"""
Tests for the `reconcile_aug_2026` statement-reconciliation command.

The command's own tables hardcode PRODUCTION tenant ids, which point at
different people in any other database — that is precisely the failure the
pre-flight guard exists to catch, so these tests monkeypatch the tables to
fixture ids and exercise the mechanics rather than the production data.

What matters here is that the risky operations are correct and repeatable:
re-pointing preserves the money and moves it to the right tenant, splitting a
quarterly transfer produces one row per month, and running the whole thing
twice changes nothing the second time.
"""
import datetime as _dt
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.buildings.models import Building, Unit, UnitStatus
from apps.payments.management.commands import reconcile_aug_2026 as cmd
from apps.payments.models import Payment
from apps.tenants.models import Tenant, TenantStatus


@pytest.fixture
def roster(db):
    """Two units, each with a retired and a current tenant — the shape the
    15-17 Aug roster correction left behind."""
    building = Building.objects.create(name="Road Block", code="RBT", total_floors=4)

    def unit(label, rent="9000"):
        return Unit.objects.create(
            building=building, label=label, monthly_rent=Decimal(rent),
            status=UnitStatus.OCCUPIED_UNPAID,
        )

    def tenant(u, first, last, *, rent="9000", move_in="2026-08-01", status=TenantStatus.ACTIVE):
        return Tenant.objects.create(
            first_name=first, last_name=last, id_number=f"T-{u.label}-{first}",
            phone="+254700000001", unit=u, monthly_rent=Decimal(rent),
            deposit_paid=Decimal("0"), move_in_date=move_in, status=status,
        )

    u201, u_com = unit("RBT201"), unit("RBT900", "60000")
    return {
        "unit201": u201,
        "unit_com": u_com,
        # Retired placeholder that the August money landed on.
        "retired": tenant(u201, "Kevin", "Placeholder", move_in="2026-06-16",
                          status=TenantStatus.MOVED_OUT),
        # The tenant who actually lives there, created 15 Aug.
        "current": tenant(u201, "Beryl", "Alinga", move_in="2026-08-01"),
        "commercial": tenant(u_com, "Ignite", "Energy", rent="60000"),
    }


def _pay(tenant, amount, *, month, ref, date=_dt.date(2026, 8, 6)):
    from apps.payments.services import process_payment

    return process_payment(
        tenant=tenant, amount=Decimal(amount), payment_date=date,
        period_month=month, period_year=2026, source="mpesa",
        reference=ref, idempotency_key=ref,
    )


def _live(tenant):
    return Payment.objects.filter(tenant=tenant, voided_at__isnull=True)


def _clear(monkeypatch, **overrides):
    """Blank every table, then set only the ones a test cares about."""
    for name in ("RELABEL_UNITS", "RENTS", "REPOINT", "RETIRE", "MISSING", "SPLITS", "NAMES"):
        monkeypatch.setattr(cmd, name, overrides.get(name, []))


class TestPreflight:
    def test_aborts_when_tenant_sits_on_a_different_unit(self, roster, monkeypatch):
        """The whole point: ids are not portable between databases."""
        _clear(monkeypatch, RENTS=[("RBT999", roster["current"].pk, Decimal("9000"), "why")])

        with pytest.raises(CommandError, match="Pre-flight failed"):
            call_command("reconcile_aug_2026", "--apply")

    def test_writes_nothing_when_preflight_fails(self, roster, monkeypatch):
        before = roster["current"].monthly_rent
        _clear(
            monkeypatch,
            RENTS=[
                ("RBT201", roster["current"].pk, Decimal("12345"), "valid row"),
                ("RBT999", roster["commercial"].pk, Decimal("1"), "bad row"),
            ],
        )
        with pytest.raises(CommandError):
            call_command("reconcile_aug_2026", "--apply")

        roster["current"].refresh_from_db()
        assert roster["current"].monthly_rent == before, "a valid row was written despite the abort"

    def test_absent_tenant_is_skipped_not_fatal(self, roster, monkeypatch):
        _clear(monkeypatch, RENTS=[("RBT201", 9_999_999, Decimal("9000"), "gone")])
        call_command("reconcile_aug_2026", "--apply")  # must not raise


class TestDryRun:
    def test_dry_run_writes_nothing(self, roster, monkeypatch):
        _clear(monkeypatch, RENTS=[("RBT201", roster["current"].pk, Decimal("20000"), "why")])
        call_command("reconcile_aug_2026")

        roster["current"].refresh_from_db()
        assert roster["current"].monthly_rent == Decimal("9000.00")


class TestRepoint:
    def test_moves_the_money_to_the_current_tenant(self, roster, monkeypatch):
        _pay(roster["retired"], "10000", month=8, ref="REF-A")
        _clear(monkeypatch, REPOINT=[
            ("REF-A", roster["retired"].pk, "RBT201", roster["current"].pk, "RBT201", "narration"),
        ])

        call_command("reconcile_aug_2026", "--apply")

        assert not _live(roster["retired"]).exists(), "money left on the retired record"
        moved = _live(roster["current"]).get()
        assert moved.amount == Decimal("10000.00")
        assert moved.reference == "REF-A"

    def test_original_is_voided_not_deleted(self, roster, monkeypatch):
        original = _pay(roster["retired"], "10000", month=8, ref="REF-A")
        _clear(monkeypatch, REPOINT=[
            ("REF-A", roster["retired"].pk, "RBT201", roster["current"].pk, "RBT201", "narration"),
        ])

        call_command("reconcile_aug_2026", "--apply")

        original.refresh_from_db()
        assert original.voided_at is not None
        assert "Re-pointed" in original.void_reason

    def test_period_never_predates_the_new_tenants_move_in(self, roster, monkeypatch):
        """FIFO had allocated this against the retired tenant's June arrears;
        the replacement tenant only moved in on 1 August."""
        _pay(roster["retired"], "9000", month=6, ref="REF-B")
        _clear(monkeypatch, REPOINT=[
            ("REF-B", roster["retired"].pk, "RBT201", roster["current"].pk, "RBT201", "narration"),
        ])

        call_command("reconcile_aug_2026", "--apply")

        moved = _live(roster["current"]).get()
        assert (moved.period_year, moved.period_month) == (2026, 8)

    def test_later_period_is_left_alone(self, roster, monkeypatch):
        _pay(roster["retired"], "9000", month=9, ref="REF-C")
        _clear(monkeypatch, REPOINT=[
            ("REF-C", roster["retired"].pk, "RBT201", roster["current"].pk, "RBT201", "narration"),
        ])

        call_command("reconcile_aug_2026", "--apply")

        assert _live(roster["current"]).get().period_month == 9

    def test_rerun_is_a_no_op(self, roster, monkeypatch):
        _pay(roster["retired"], "10000", month=8, ref="REF-A")
        _clear(monkeypatch, REPOINT=[
            ("REF-A", roster["retired"].pk, "RBT201", roster["current"].pk, "RBT201", "narration"),
        ])

        call_command("reconcile_aug_2026", "--apply")
        call_command("reconcile_aug_2026", "--apply")

        assert _live(roster["current"]).count() == 1, "re-running double-booked the payment"


class TestSplit:
    def test_quarterly_transfer_becomes_three_monthly_rows(self, roster, monkeypatch):
        _pay(roster["commercial"], "180000", month=8, ref="REF-Q")
        _clear(monkeypatch, SPLITS=[("REF-Q", roster["commercial"].pk, "RBT900", Decimal("60000"))])

        call_command("reconcile_aug_2026", "--apply")

        rows = _live(roster["commercial"]).order_by("period_year", "period_month")
        assert [(r.period_year, r.period_month) for r in rows] == [(2026, 8), (2026, 9), (2026, 10)]
        assert {r.amount for r in rows} == {Decimal("60000.00")}
        assert sum(r.amount for r in rows) == Decimal("180000.00"), "split changed the total"

    def test_leaves_a_lump_that_is_not_an_exact_multiple(self, roster, monkeypatch):
        _pay(roster["commercial"], "175000", month=8, ref="REF-Q")
        _clear(monkeypatch, SPLITS=[("REF-Q", roster["commercial"].pk, "RBT900", Decimal("60000"))])

        call_command("reconcile_aug_2026", "--apply")

        row = _live(roster["commercial"]).get()
        assert row.amount == Decimal("175000.00"), "an unexpected amount was split anyway"

    def test_rerun_is_a_no_op(self, roster, monkeypatch):
        _pay(roster["commercial"], "180000", month=8, ref="REF-Q")
        _clear(monkeypatch, SPLITS=[("REF-Q", roster["commercial"].pk, "RBT900", Decimal("60000"))])

        call_command("reconcile_aug_2026", "--apply")
        call_command("reconcile_aug_2026", "--apply")

        assert _live(roster["commercial"]).count() == 3


class TestMissingPayments:
    def test_records_the_statement_payment(self, roster, monkeypatch):
        _clear(monkeypatch, MISSING=[
            (roster["current"].pk, "RBT201", Decimal("110000"), "bank", "never captured"),
        ])

        call_command("reconcile_aug_2026", "--apply")

        row = _live(roster["current"]).get()
        assert row.amount == Decimal("110000.00")
        assert row.payment_date == cmd.STATEMENT_DATE
        assert (row.period_year, row.period_month) == (2026, 8)

    def test_rerun_does_not_double_book(self, roster, monkeypatch):
        _clear(monkeypatch, MISSING=[
            (roster["current"].pk, "RBT201", Decimal("110000"), "bank", "never captured"),
        ])

        call_command("reconcile_aug_2026", "--apply")
        call_command("reconcile_aug_2026", "--apply")

        assert _live(roster["current"]).count() == 1


class TestRentsAndNames:
    def test_rent_is_raised_to_the_statement_figure(self, roster, monkeypatch):
        _clear(monkeypatch, RENTS=[
            ("RBT201", roster["current"].pk, Decimal("20000"), "rent + service charge"),
        ])

        call_command("reconcile_aug_2026", "--apply")

        roster["current"].refresh_from_db()
        assert roster["current"].monthly_rent == Decimal("20000.00")

    def test_name_is_corrected(self, roster, monkeypatch):
        _clear(monkeypatch, NAMES=[(roster["current"].pk, "RBT201", "Mariane", "Mukabwa")])

        call_command("reconcile_aug_2026", "--apply")

        roster["current"].refresh_from_db()
        assert roster["current"].full_name == "Mariane Mukabwa"


class TestRetire:
    def test_refuses_while_live_payments_remain(self, roster, monkeypatch):
        _pay(roster["retired"], "10000", month=8, ref="REF-A")
        _clear(monkeypatch, RETIRE=[(roster["retired"].pk, "RBT201", "duplicate")])

        call_command("reconcile_aug_2026", "--apply")

        roster["retired"].refresh_from_db()
        assert roster["retired"].status == TenantStatus.MOVED_OUT, "archived with money still on it"

    def test_archives_once_the_money_has_moved(self, roster, monkeypatch):
        _pay(roster["retired"], "10000", month=8, ref="REF-A")
        _clear(
            monkeypatch,
            REPOINT=[("REF-A", roster["retired"].pk, "RBT201",
                      roster["current"].pk, "RBT201", "narration")],
            RETIRE=[(roster["retired"].pk, "RBT201", "duplicate")],
        )

        call_command("reconcile_aug_2026", "--apply")

        roster["retired"].refresh_from_db()
        assert roster["retired"].status == TenantStatus.ARCHIVED


class TestUnitRelabel:
    def test_renames_and_keeps_the_old_label_as_an_alias(self, roster, monkeypatch):
        _clear(monkeypatch, RELABEL_UNITS=[("RBT201", "RBT0201", "statement spelling")])

        call_command("reconcile_aug_2026", "--apply")

        unit = roster["unit201"]
        unit.refresh_from_db()
        assert unit.label == "RBT0201"
        assert unit.aliases.filter(label="RBT201").exists(), "old reference would stop matching"

    def test_rerun_is_a_no_op(self, roster, monkeypatch):
        _clear(monkeypatch, RELABEL_UNITS=[("RBT201", "RBT0201", "statement spelling")])

        call_command("reconcile_aug_2026", "--apply")
        call_command("reconcile_aug_2026", "--apply")

        assert roster["unit201"].aliases.count() == 1


class TestZeroBillRepair:
    """A row raised while the tenant's rent was 0.00 keeps swallowing cash:
    nothing in the normal flow rewrites an existing obligation, and
    backfill_arrears skips any period that already has a row."""

    def _arrears(self, tenant, month, *, rent="0", paid="0"):
        from apps.payments.models import Arrears

        return Arrears.objects.create(
            tenant=tenant, period_month=month, period_year=2026,
            expected_rent=Decimal(rent), expected_vat=Decimal("0"),
            amount_paid=Decimal(paid), balance=Decimal("0"), is_cleared=True,
        )

    def test_repairs_a_zero_row_that_holds_cash(self, roster, monkeypatch):
        tenant = roster["current"]
        self._arrears(tenant, 8, rent="0", paid="9000")
        _pay(tenant, "9000", month=8, ref="REF-Z")
        _clear(monkeypatch)

        call_command("reconcile_aug_2026", "--apply")

        from apps.payments.models import Arrears
        arr = Arrears.objects.get(tenant=tenant, period_month=8)
        assert arr.expected_rent == Decimal("9000.00"), "obligation still zero"
        assert arr.balance == Decimal("0.00")
        assert arr.is_cleared is True

    def test_leaves_a_zero_row_with_no_cash_alone(self, roster, monkeypatch):
        """A clean cutover month attracts no payment. Inventing a month's rent
        for it is the corruption this repair exists to avoid repeating."""
        tenant = roster["current"]
        self._arrears(tenant, 6, rent="0", paid="0")
        _clear(monkeypatch)

        call_command("reconcile_aug_2026", "--apply")

        from apps.payments.models import Arrears
        assert Arrears.objects.get(tenant=tenant, period_month=6).expected_rent == Decimal("0.00")

    def test_leaves_a_normally_billed_row_alone(self, roster, monkeypatch):
        tenant = roster["current"]
        self._arrears(tenant, 7, rent="9000", paid="4000")
        _clear(monkeypatch)

        call_command("reconcile_aug_2026", "--apply")

        from apps.payments.models import Arrears
        arr = Arrears.objects.get(tenant=tenant, period_month=7)
        assert arr.expected_rent == Decimal("9000.00")
        assert arr.amount_paid == Decimal("4000.00")

    def test_underpayment_is_left_owing_not_cleared(self, roster, monkeypatch):
        tenant = roster["current"]
        self._arrears(tenant, 8, rent="0", paid="4000")
        _pay(tenant, "4000", month=8, ref="REF-Z")
        _clear(monkeypatch)

        call_command("reconcile_aug_2026", "--apply")

        from apps.payments.models import Arrears
        arr = Arrears.objects.get(tenant=tenant, period_month=8)
        assert arr.balance == Decimal("5000.00"), "partial payment reported as settled"
        assert arr.is_cleared is False

    def test_rerun_is_a_no_op(self, roster, monkeypatch):
        tenant = roster["current"]
        self._arrears(tenant, 8, rent="0", paid="9000")
        _pay(tenant, "9000", month=8, ref="REF-Z")
        _clear(monkeypatch)

        call_command("reconcile_aug_2026", "--apply")
        call_command("reconcile_aug_2026", "--apply")

        from apps.payments.models import Arrears
        assert Arrears.objects.get(tenant=tenant, period_month=8).expected_rent == Decimal("9000.00")
