"""
Tests for applying Dr Osoro's answers on the Matasia Commercial queries.

The two that matter: archiving a tenancy must never strand money on it, and
correcting a payment's channel must preserve the amount while leaving both the
reversal and the replacement in the ledger.
"""
import datetime as _dt
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.buildings.models import Building, Unit, UnitClassification, UnitStatus
from apps.payments.management.commands import apply_matasia_answers as cmd
from apps.payments.models import Payment
from apps.tenants.models import Tenant, TenantStatus

D = Decimal


@pytest.fixture
def arcade(db):
    building = Building.objects.create(name="Matasia Arcade", code="MCQ", total_floors=2)

    def let(label, rent="24000"):
        unit = Unit.objects.create(
            building=building, label=label, monthly_rent=D(rent),
            classification=UnitClassification.BUSINESS, status=UnitStatus.OCCUPIED_UNPAID,
        )
        tenant = Tenant.objects.create(
            first_name=label, last_name="Ltd", id_number=f"Q-{label}",
            phone="+254700000004", unit=unit, monthly_rent=D(rent),
            deposit_paid=D(0), move_in_date="2026-07-01", status=TenantStatus.ACTIVE,
        )
        return unit, tenant

    ghost_unit, ghost = let("MCQ04")
    payer_unit, payer = let("MCQ12", "50655")
    return {
        "building": building,
        "ghost_unit": ghost_unit, "ghost": ghost,
        "payer_unit": payer_unit, "payer": payer,
    }


def _plan(monkeypatch, *, vacate=(), create=(), channels=()):
    monkeypatch.setattr(cmd, "VACATE", list(vacate))
    monkeypatch.setattr(cmd, "CREATE_UNITS", list(create))
    monkeypatch.setattr(cmd, "CHANNELS", list(channels))


def _pay(tenant, amount, key, source="bank"):
    from apps.payments.services import process_payment

    return process_payment(
        tenant=tenant, amount=D(amount), payment_date=_dt.date(2026, 8, 21),
        period_month=8, period_year=2026, source=source,
        reference=key, idempotency_key=key,
    )


def _live(tenant):
    return Payment.objects.filter(tenant=tenant, voided_at__isnull=True)


class TestPreflight:
    def test_aborts_when_the_id_is_on_another_unit(self, arcade, monkeypatch):
        _plan(monkeypatch, vacate=[("MCQ99", arcade["ghost"].pk, "why")])

        with pytest.raises(CommandError, match="Pre-flight failed"):
            call_command("apply_matasia_answers", "--apply")


class TestVacate:
    def test_archives_the_tenancy_and_frees_the_unit(self, arcade, monkeypatch):
        _plan(monkeypatch, vacate=[("MCQ04", arcade["ghost"].pk, "confirmed vacant")])

        call_command("apply_matasia_answers", "--apply")

        arcade["ghost"].refresh_from_db()
        arcade["ghost_unit"].refresh_from_db()
        assert arcade["ghost"].status == TenantStatus.ARCHIVED
        assert arcade["ghost_unit"].status == UnitStatus.VACANT
        assert arcade["ghost_unit"].monthly_rent == D("0.00")

    def test_refuses_to_archive_a_tenancy_holding_money(self, arcade, monkeypatch):
        """Vacating a unit that has taken cash would strand the payment on an
        archived record, exactly the failure the roster correction caused."""
        _pay(arcade["ghost"], "25000", "Q-KEEP")
        _plan(monkeypatch, vacate=[("MCQ04", arcade["ghost"].pk, "confirmed vacant")])

        call_command("apply_matasia_answers", "--apply")

        arcade["ghost"].refresh_from_db()
        assert arcade["ghost"].status == TenantStatus.ACTIVE
        assert _live(arcade["ghost"]).count() == 1

    def test_rerun_is_a_no_op(self, arcade, monkeypatch):
        _plan(monkeypatch, vacate=[("MCQ04", arcade["ghost"].pk, "confirmed vacant")])

        call_command("apply_matasia_answers", "--apply")
        call_command("apply_matasia_answers", "--apply")

        arcade["ghost"].refresh_from_db()
        assert arcade["ghost"].status == TenantStatus.ARCHIVED


class TestCreateUnit:
    def test_creates_the_missing_unit_as_vacant(self, arcade, monkeypatch):
        _plan(monkeypatch, create=[("MCQ20", "MCQ", 1, "shop")])

        call_command("apply_matasia_answers", "--apply")

        unit = Unit.objects.get(label="MCQ20")
        assert unit.status == UnitStatus.VACANT
        assert unit.monthly_rent == D("0.00")
        assert unit.floor == 1

    def test_rerun_does_not_duplicate(self, arcade, monkeypatch):
        _plan(monkeypatch, create=[("MCQ20", "MCQ", 1, "shop")])

        call_command("apply_matasia_answers", "--apply")
        call_command("apply_matasia_answers", "--apply")

        assert Unit.objects.filter(label="MCQ20").count() == 1

    def test_unknown_building_is_skipped_not_fatal(self, arcade, monkeypatch):
        _plan(monkeypatch, create=[("ZZZ01", "NOPE", 1, "shop")])

        call_command("apply_matasia_answers", "--apply")  # must not raise

        assert not Unit.objects.filter(label="ZZZ01").exists()


class TestPaymentChannel:
    def test_corrects_the_channel_and_keeps_the_amount(self, arcade, monkeypatch):
        _pay(arcade["payer"], "58760", "STMT-Q-MCF12", source="bank")
        _plan(monkeypatch, channels=[
            ("STMT-Q-MCF12", "MCQ12", arcade["payer"].pk, "cheque", "paid by cheque"),
        ])

        call_command("apply_matasia_answers", "--apply")

        live = _live(arcade["payer"])
        assert live.count() == 1
        row = live.get()
        assert row.source == "cheque"
        assert row.amount == D("58760.00"), "the correction changed the amount"

    def test_the_original_is_voided_not_deleted(self, arcade, monkeypatch):
        original = _pay(arcade["payer"], "58760", "STMT-Q-MCF12", source="bank")
        _plan(monkeypatch, channels=[
            ("STMT-Q-MCF12", "MCQ12", arcade["payer"].pk, "cheque", "paid by cheque"),
        ])

        call_command("apply_matasia_answers", "--apply")

        original.refresh_from_db()
        assert original.voided_at is not None
        assert "cheque" in original.void_reason

    def test_period_and_date_survive(self, arcade, monkeypatch):
        _pay(arcade["payer"], "58760", "STMT-Q-MCF12", source="bank")
        _plan(monkeypatch, channels=[
            ("STMT-Q-MCF12", "MCQ12", arcade["payer"].pk, "cheque", "paid by cheque"),
        ])

        call_command("apply_matasia_answers", "--apply")

        row = _live(arcade["payer"]).get()
        assert (row.period_year, row.period_month) == (2026, 8)
        assert row.payment_date == _dt.date(2026, 8, 21)

    def test_already_correct_channel_is_left_alone(self, arcade, monkeypatch):
        original = _pay(arcade["payer"], "58760", "STMT-Q-MCF12", source="cheque")
        _plan(monkeypatch, channels=[
            ("STMT-Q-MCF12", "MCQ12", arcade["payer"].pk, "cheque", "paid by cheque"),
        ])

        call_command("apply_matasia_answers", "--apply")

        original.refresh_from_db()
        assert original.voided_at is None, "a correctly-channelled payment was churned"

    def test_rerun_does_not_double_book(self, arcade, monkeypatch):
        _pay(arcade["payer"], "58760", "STMT-Q-MCF12", source="bank")
        _plan(monkeypatch, channels=[
            ("STMT-Q-MCF12", "MCQ12", arcade["payer"].pk, "cheque", "paid by cheque"),
        ])

        call_command("apply_matasia_answers", "--apply")
        call_command("apply_matasia_answers", "--apply")

        assert _live(arcade["payer"]).count() == 1


class TestDryRun:
    def test_writes_nothing(self, arcade, monkeypatch):
        _pay(arcade["payer"], "58760", "STMT-Q-MCF12", source="bank")
        _plan(
            monkeypatch,
            vacate=[("MCQ04", arcade["ghost"].pk, "confirmed vacant")],
            create=[("MCQ20", "MCQ", 1, "shop")],
            channels=[("STMT-Q-MCF12", "MCQ12", arcade["payer"].pk, "cheque", "cheque")],
        )

        call_command("apply_matasia_answers")

        arcade["ghost"].refresh_from_db()
        assert arcade["ghost"].status == TenantStatus.ACTIVE
        assert not Unit.objects.filter(label="MCQ20").exists()
        assert _live(arcade["payer"]).get().source == "bank"


class TestDeposits:
    def test_records_the_deposit(self, arcade, monkeypatch):
        monkeypatch.setattr(cmd, "VACATE", [])
        monkeypatch.setattr(cmd, "CREATE_UNITS", [])
        monkeypatch.setattr(cmd, "CHANNELS", [])
        monkeypatch.setattr(cmd, "DISCARD_PERIODS", [])
        monkeypatch.setattr(cmd, "DEPOSITS", [("MCQ04", arcade["ghost"].pk, D("72000"), "3 x 24,000")])

        call_command("apply_matasia_answers", "--apply")

        arcade["ghost"].refresh_from_db()
        assert arcade["ghost"].deposit_paid == D("72000.00")

    def test_rerun_is_a_no_op(self, arcade, monkeypatch):
        monkeypatch.setattr(cmd, "VACATE", [])
        monkeypatch.setattr(cmd, "CREATE_UNITS", [])
        monkeypatch.setattr(cmd, "CHANNELS", [])
        monkeypatch.setattr(cmd, "DISCARD_PERIODS", [])
        monkeypatch.setattr(cmd, "DEPOSITS", [("MCQ04", arcade["ghost"].pk, D("72000"), "3 x 24,000")])

        call_command("apply_matasia_answers", "--apply")
        call_command("apply_matasia_answers", "--apply")

        arcade["ghost"].refresh_from_db()
        assert arcade["ghost"].deposit_paid == D("72000.00")


class TestDiscardPeriod:
    def _only(self, monkeypatch, discard):
        monkeypatch.setattr(cmd, "VACATE", [])
        monkeypatch.setattr(cmd, "CREATE_UNITS", [])
        monkeypatch.setattr(cmd, "CHANNELS", [])
        monkeypatch.setattr(cmd, "DEPOSITS", [])
        monkeypatch.setattr(cmd, "DISCARD_PERIODS", discard)

    def _june(self, tenant, rent="22500", vat="3600", paid="0"):
        from apps.payments.models import Arrears

        return Arrears.objects.create(
            tenant=tenant, period_year=2026, period_month=6,
            expected_rent=D(rent), expected_vat=D(vat),
            amount_paid=D(paid), balance=D(rent) + D(vat) - D(paid),
        )

    def test_voids_the_payment_and_removes_the_charge(self, arcade, monkeypatch):
        from apps.payments.models import Arrears

        tenant = arcade["payer"]
        self._june(tenant)
        pay = _pay(tenant, "21880", "Q-JUN", source="mpesa")
        Payment.objects.filter(pk=pay.pk).update(period_month=6)
        self._only(monkeypatch, [("MCQ12", tenant.pk, 2026, 6, "struck out")])

        call_command("apply_matasia_answers", "--apply")

        pay.refresh_from_db()
        assert pay.voided_at is not None, "the receipt was deleted rather than voided"
        assert not Arrears.objects.filter(tenant=tenant, period_month=6).exists()

    def test_the_receipt_survives_as_a_voided_row(self, arcade, monkeypatch):
        """Cash that was genuinely banked stays traceable — the reversal is the
        audit trail, deletion would erase it."""
        tenant = arcade["payer"]
        self._june(tenant)
        pay = _pay(tenant, "21880", "Q-JUN", source="mpesa")
        Payment.objects.filter(pk=pay.pk).update(period_month=6)
        self._only(monkeypatch, [("MCQ12", tenant.pk, 2026, 6, "struck out")])

        call_command("apply_matasia_answers", "--apply")

        assert Payment.objects.filter(pk=pay.pk).exists()

    def test_later_periods_are_untouched(self, arcade, monkeypatch):
        tenant = arcade["payer"]
        self._june(tenant)
        august = _pay(tenant, "22500", "Q-AUG", source="mpesa")
        self._only(monkeypatch, [("MCQ12", tenant.pk, 2026, 6, "struck out")])

        call_command("apply_matasia_answers", "--apply")

        august.refresh_from_db()
        assert august.voided_at is None, "August was caught by a June strike-out"

    def test_rerun_is_a_no_op(self, arcade, monkeypatch):
        tenant = arcade["payer"]
        self._june(tenant)
        pay = _pay(tenant, "21880", "Q-JUN", source="mpesa")
        Payment.objects.filter(pk=pay.pk).update(period_month=6)
        self._only(monkeypatch, [("MCQ12", tenant.pk, 2026, 6, "struck out")])

        call_command("apply_matasia_answers", "--apply")
        call_command("apply_matasia_answers", "--apply")

        assert Payment.objects.filter(tenant=tenant, voided_at__isnull=True, period_month=6).count() == 0


class TestStrikeOutScope:
    """Guards on the live DISCARD_PERIODS table itself, not the mechanism.

    Both invariants are easy to break by adding one plausible-looking row, and
    neither failure would be obvious afterwards — the numbers would just be
    quietly wrong on the statement."""

    def test_july_is_never_struck_out(self):
        """July 2026 holds the opening balances seeded from the statement's
        B/Forward column. Striking it would zero every August total payable."""
        july = [row for row in cmd.DISCARD_PERIODS if (row[2], row[3]) == (2026, 7)]
        assert july == [], f"July strike-out would destroy the B/Forward openings: {july}"

    def test_scope_is_commercial_only(self):
        """Matasia residential has no B/Forward loaded, so clearing its history
        would open those tenancies at nil against a sheet that says otherwise."""
        residential = [row for row in cmd.DISCARD_PERIODS if row[0].upper().startswith("MR")]
        assert residential == [], f"residential struck out without openings loaded: {residential}"


class TestDepositRule:
    """Every commercial deposit on the live table must be exactly 3x rent.

    The figures in the original roll only followed the rule for five of twelve
    tenancies, so a stray transcribed number is the likely way this drifts."""

    RENTS = {
        "MCG01": D("24000"), "MCG02": D("22500"), "MCG03": D("18000"),
        "MCG05": D("86500"), "MCG10": D("25000"), "MCF01": D("25000"),
        "MCF04": D("25000"), "MCF12": D("50655"), "MCF13": D("24000"),
    }

    def test_every_deposit_is_three_months_rent(self):
        wrong = [
            f"{label}: {amount} != 3 x {self.RENTS[label]}"
            for label, _tid, amount, _why in cmd.DEPOSITS
            if label in self.RENTS and amount != self.RENTS[label] * 3
        ]
        assert wrong == [], f"deposits off the 3x rule: {wrong}"

    def test_no_duplicate_units(self):
        labels = [row[0] for row in cmd.DEPOSITS]
        assert len(labels) == len(set(labels)), f"a unit is listed twice: {labels}"
