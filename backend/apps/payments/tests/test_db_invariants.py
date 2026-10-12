"""The database refuses what only Python used to refuse.

Several rules the books depend on were enforced by a serializer, or implicitly
by whichever service function happened to raise first. A serializer guards the
API. It does not guard a management command, a Django-admin save, a data
migration, or a psql session — and this system has twenty management commands
that write financial records directly.

Each test below writes through the ORM with validation bypassed, which is what
those other paths effectively do, and asserts the database itself says no.

`config/db_invariants.py` documents why each rule exists;
`manage.py check_db_invariants` reports violations against live data before the
constraint migration is deployed.
"""
import datetime as dt
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from apps.buildings.models import Building, Unit, UnitClassification, UnitStatus
from apps.expenses.models import Account, AccountType, Expense, ExpenseCategory, ManualIncome
from apps.payments.models import Payment, PaymentType, UtilityCharge
from apps.tenants.models import Tenant, TenantStatus


@pytest.fixture
def world(db):
    building = Building.objects.create(name="Invariant Block", code="IV", total_floors=1)
    unit = Unit.objects.create(
        building=building, label="IV1", monthly_rent=Decimal("10000"),
        classification=UnitClassification.RESIDENTIAL, status=UnitStatus.OCCUPIED_UNPAID,
    )
    tenant = Tenant.objects.create(
        first_name="Inv", last_name="Ariant", id_number="INV-1",
        phone="+254700000444", unit=unit, monthly_rent=Decimal("10000"),
        move_in_date=dt.date(2026, 1, 1), status=TenantStatus.ACTIVE,
    )
    account, _ = Account.objects.get_or_create(
        code="5200",
        defaults={"name": "Repairs", "account_type": AccountType.EXPENSE, "parent_code": "5000"},
    )
    income_account, _ = Account.objects.get_or_create(
        code="4300",
        defaults={"name": "Farm", "account_type": AccountType.INCOME, "parent_code": "4000"},
    )
    category, _ = ExpenseCategory.objects.get_or_create(
        name="Repairs & Maintenance", defaults={"account": account},
    )
    return {
        "building": building, "unit": unit, "tenant": tenant,
        "category": category, "income_account": income_account,
    }


def _payment(tenant, **overrides):
    return dict(
        tenant=tenant, amount=Decimal("1000"), payment_date=dt.date(2026, 6, 5),
        period_month=6, period_year=2026, payment_type=PaymentType.RENT,
    ) | overrides


# ── Payment ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("amount", [Decimal("0"), Decimal("-1"), Decimal("-10000")])
def test_a_non_positive_payment_cannot_be_written(world, amount):
    """A zero or negative receipt corrupts every sum that reads Payment.amount.

    `split_tax_inclusive` already rejects it on the service path, and migration
    0017 removed the legacy negative "VOID:" rows. This makes the guarantee
    structural instead of a property of call order.
    """
    with pytest.raises(IntegrityError), transaction.atomic():
        Payment.objects.create(**_payment(world["tenant"], amount=amount))


@pytest.mark.parametrize("month", [0, 13, 99])
def test_a_payment_cannot_be_filed_to_an_impossible_month(world, month):
    """Such a row vanishes from every period-keyed report and reconciles to nothing."""
    with pytest.raises(IntegrityError), transaction.atomic():
        Payment.objects.create(**_payment(world["tenant"], period_month=month))


def test_a_valid_payment_is_still_accepted(world):
    """The constraints must not have been drawn so tightly that normal work fails."""
    payment = Payment.objects.create(**_payment(world["tenant"]))
    assert payment.pk


# ── UtilityCharge ───────────────────────────────────────────────────────────

def test_a_second_water_charge_for_the_same_meter_and_month_is_refused(world):
    """The double-billing race, closed at the database.

    Both writers — the staff meter form and the spreadsheet importer — use
    `update_or_create` on (tenant, period, label). Under concurrency both read
    nothing, both insert, and the tenant is billed twice for the same water with
    two journal entries to match. `update_or_create` cannot prevent that; a
    unique constraint can.
    """
    common = dict(
        tenant=world["tenant"], period_month=6, period_year=2026,
        label="Water Usage", posting_date=dt.date(2026, 6, 30),
    )
    UtilityCharge.objects.create(amount=Decimal("1400"), **common)

    with pytest.raises(IntegrityError), transaction.atomic():
        UtilityCharge.objects.create(amount=Decimal("1400"), **common)


def test_a_different_meter_in_the_same_month_is_fine(world):
    """The constraint is per METER, not per month — electricity is not water."""
    common = dict(
        tenant=world["tenant"], period_month=6, period_year=2026,
        posting_date=dt.date(2026, 6, 30),
    )
    UtilityCharge.objects.create(label="Water Usage", amount=Decimal("1400"), **common)
    other = UtilityCharge.objects.create(label="Electricity", amount=Decimal("900"), **common)
    assert other.pk


def test_a_negative_utility_charge_is_still_allowed(world):
    """A credit note. `ledger.posting.post_utility_charge` has a branch for it.

    Deliberately NOT constrained — this test exists so nobody "tidies up" by
    adding an amount > 0 check to match Payment and Expense, which would break a
    supported operation.
    """
    charge = UtilityCharge.objects.create(
        tenant=world["tenant"], period_month=7, period_year=2026,
        label="Water Usage", posting_date=dt.date(2026, 7, 31),
        amount=Decimal("-200"),
    )
    assert charge.amount == Decimal("-200")


# ── Expense / ManualIncome ──────────────────────────────────────────────────

@pytest.mark.parametrize("amount", [Decimal("0"), Decimal("-50")])
def test_a_non_positive_expense_cannot_be_written(world, amount):
    with pytest.raises(IntegrityError), transaction.atomic():
        Expense.objects.create(
            date=dt.date(2026, 6, 1), building=world["building"],
            category=world["category"], amount=amount, description="x",
            period_month=6, period_year=2026,
        )


def test_an_expense_cannot_be_filed_to_month_zero(world):
    with pytest.raises(IntegrityError), transaction.atomic():
        Expense.objects.create(
            date=dt.date(2026, 6, 1), building=world["building"],
            category=world["category"], amount=Decimal("100"), description="x",
            period_month=0, period_year=2026,
        )


def test_a_non_positive_manual_income_cannot_be_written(world):
    with pytest.raises(IntegrityError), transaction.atomic():
        ManualIncome.objects.create(
            date=dt.date(2026, 6, 1), building=world["building"],
            account=world["income_account"], amount=Decimal("0"),
            description="x", period_month=6, period_year=2026,
        )


# ── Rents, deposits, due day ────────────────────────────────────────────────

def test_a_unit_rent_cannot_go_negative(world):
    """`adjust-rent` rewrites this across a whole building at once.

    It used float arithmetic with no lower bound; a negative rent inverts every
    obligation derived from it.
    """
    unit = world["unit"]
    unit.monthly_rent = Decimal("-1")
    with pytest.raises(IntegrityError), transaction.atomic():
        unit.save(update_fields=["monthly_rent"])


def test_a_tenant_rent_and_deposit_cannot_go_negative(world):
    tenant = world["tenant"]
    tenant.monthly_rent = Decimal("-1")
    with pytest.raises(IntegrityError), transaction.atomic():
        tenant.save(update_fields=["monthly_rent"])

    tenant.refresh_from_db()
    tenant.deposit_paid = Decimal("-1")
    with pytest.raises(IntegrityError), transaction.atomic():
        tenant.save(update_fields=["deposit_paid"])


@pytest.mark.parametrize("due_day", [0, 32, 200])
def test_an_impossible_due_day_cannot_be_stored(world, due_day):
    """`send_rent_reminders` builds date(year, month, due_day).

    A zero raises ValueError inside the daily loop and takes the whole run down
    for EVERY tenant, not just the one with the bad value. Model validators do
    not run on `.save()`, so only the database can stop this.
    """
    tenant = world["tenant"]
    tenant.due_day = due_day
    with pytest.raises(IntegrityError), transaction.atomic():
        tenant.save(update_fields=["due_day"])


@pytest.mark.parametrize("pct", [Decimal("-1"), Decimal("101"), Decimal("999")])
def test_a_deposit_refund_percentage_outside_0_100_is_refused(world, pct):
    """The move-out view multiplies `deposit_paid` by this figure."""
    tenant = world["tenant"]
    tenant.deposit_refund_percentage = pct
    with pytest.raises(IntegrityError), transaction.atomic():
        tenant.save(update_fields=["deposit_refund_percentage"])


# ── The pre-flight and its command ──────────────────────────────────────────

def test_the_invariant_scan_reports_clean_data(world):
    from django.apps import apps as global_apps

    from config.db_invariants import duplicate_utility_charges, violations

    Payment.objects.create(**_payment(world["tenant"]))
    assert violations(global_apps) == []
    assert duplicate_utility_charges(global_apps) == []


def test_the_invariant_scan_finds_a_planted_violation(world):
    """Proves the pre-flight would actually stop a deploy, rather than always passing.

    The row is planted with the check suppressed, exactly as a pre-constraint
    production database would hold it.
    """
    from django.apps import apps as global_apps
    from django.db import connection

    from config.db_invariants import format_report, violations

    with connection.cursor() as cursor:
        if connection.vendor == "sqlite":
            cursor.execute("PRAGMA ignore_check_constraints = ON")
        else:
            cursor.execute(
                'ALTER TABLE "tenants_tenant" DROP CONSTRAINT IF EXISTS "tenant_due_day_valid"'
            )
    try:
        Tenant.objects.filter(pk=world["tenant"].pk).update(due_day=0)
        broken = violations(global_apps)
        assert any(item["rule"].startswith("Tenant.due_day") for item in broken)
        assert "tenants.Tenant" in format_report(broken, [])
    finally:
        Tenant.objects.filter(pk=world["tenant"].pk).update(due_day=5)
        with connection.cursor() as cursor:
            if connection.vendor == "sqlite":
                cursor.execute("PRAGMA ignore_check_constraints = OFF")
            else:
                cursor.execute(
                    'ALTER TABLE "tenants_tenant" ADD CONSTRAINT "tenant_due_day_valid" '
                    "CHECK (due_day >= 1 AND due_day <= 31)"
                )
