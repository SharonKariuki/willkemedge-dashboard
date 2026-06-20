"""
pytest tests for apps.ledger.

Run with:  pytest apps/ledger/tests/ -v
"""
import datetime
from decimal import Decimal

import pytest

# ── fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def building(db):
    from apps.buildings.models import Building
    return Building.objects.create(name="Test Building", address="1 Test St")


@pytest.fixture
def residential_unit(db, building):
    from apps.buildings.models import Unit, UnitClassification
    return Unit.objects.create(
        building=building,
        label="A1",
        classification=UnitClassification.RESIDENTIAL,
        monthly_rent=Decimal("25000.00"),
    )


@pytest.fixture
def commercial_unit(db, building):
    from apps.buildings.models import Unit, UnitClassification
    return Unit.objects.create(
        building=building,
        label="B1",
        classification=UnitClassification.BUSINESS,
        monthly_rent=Decimal("50000.00"),
    )


@pytest.fixture
def residential_tenant(db, residential_unit):
    from apps.tenants.models import Tenant, TenantStatus
    return Tenant.objects.create(
        first_name="Alice",
        last_name="Wanjiku",
        id_number="ID001",
        phone="0700000001",
        unit=residential_unit,
        monthly_rent=Decimal("25000.00"),
        status=TenantStatus.ACTIVE,
        move_in_date=datetime.date(2024, 1, 1),
        deposit_paid=Decimal("25000.00"),
    )


@pytest.fixture
def commercial_tenant(db, commercial_unit):
    from apps.tenants.models import Tenant, TenantStatus
    return Tenant.objects.create(
        first_name="Biz",
        last_name="Ltd",
        id_number="ID002",
        phone="0700000002",
        unit=commercial_unit,
        monthly_rent=Decimal("50000.00"),
        status=TenantStatus.ACTIVE,
        move_in_date=datetime.date(2024, 1, 1),
        deposit_paid=Decimal("50000.00"),
    )


@pytest.fixture
def expense_category(db):
    from apps.expenses.models import Account, ExpenseCategory
    account = Account.objects.get(code="5200")  # seeded COA
    return ExpenseCategory.objects.create(name="Repairs", account=account)


def _make_payment(tenant, amount, payment_type, month=4, year=2026):
    from apps.payments.models import Payment
    # Use Payment.objects.create — signals will fire but we'll test posting directly
    p = Payment(
        tenant=tenant,
        amount=Decimal(str(amount)),
        payment_date=datetime.date(year, month, 15),
        period_month=month,
        period_year=year,
        payment_type=payment_type,
        reference="TEST-001",
    )
    p.save()
    return p


def _make_expense(category, amount, building=None, method="bank"):
    from apps.expenses.models import Expense
    e = Expense(
        date=datetime.date(2026, 4, 15),
        category=category,
        amount=Decimal(str(amount)),
        description="Test expense",
        period_month=4,
        period_year=2026,
        building=building,
        payment_method=method,
    )
    e.save()
    return e


# ── posting balance tests ────────────────────────────────────────────────────

@pytest.mark.django_db
def test_post_rent_payment_balances(residential_tenant):
    # Skip signal-created entry if any, test directly
    from apps.ledger.models import JournalEntry
    from apps.ledger.posting import post_payment
    from apps.payments.models import PaymentType
    JournalEntry.objects.filter(source_type="payment").delete()

    payment = _make_payment(residential_tenant, "25000.00", PaymentType.RENT)
    JournalEntry.objects.filter(source_type="payment").delete()

    entry = post_payment(payment)
    lines = list(entry.lines.all())

    total_debit = sum(line.debit for line in lines)
    total_credit = sum(line.credit for line in lines)
    assert total_debit == total_credit, f"Entry not balanced: DR={total_debit} CR={total_credit}"


@pytest.mark.django_db
def test_residential_rent_credits_4110(residential_tenant):
    from apps.ledger.models import JournalEntry
    from apps.ledger.posting import post_payment
    from apps.payments.models import PaymentType

    JournalEntry.objects.filter(source_type="payment").delete()
    payment = _make_payment(residential_tenant, "25000.00", PaymentType.RENT)
    JournalEntry.objects.filter(source_type="payment").delete()

    entry = post_payment(payment)
    credit_codes = [line.account.code for line in entry.lines.all() if line.credit > 0]
    assert "4110" in credit_codes, f"Expected 4110 in credit lines, got: {credit_codes}"


@pytest.mark.django_db
def test_commercial_rent_credits_4120(commercial_tenant):
    from apps.ledger.models import JournalEntry
    from apps.ledger.posting import post_payment
    from apps.payments.models import PaymentType

    JournalEntry.objects.filter(source_type="payment").delete()
    payment = _make_payment(commercial_tenant, "50000.00", PaymentType.RENT)
    JournalEntry.objects.filter(source_type="payment").delete()

    entry = post_payment(payment)
    credit_codes = [line.account.code for line in entry.lines.all() if line.credit > 0]
    assert "4120" in credit_codes, f"Expected 4120 in credit lines, got: {credit_codes}"


@pytest.mark.django_db
def test_late_fee_payment_balances(residential_tenant):
    from apps.ledger.models import JournalEntry
    from apps.ledger.posting import post_payment
    from apps.payments.models import PaymentType

    JournalEntry.objects.filter(source_type="payment").delete()
    payment = _make_payment(residential_tenant, "1500.00", PaymentType.LATE_FEE)
    JournalEntry.objects.filter(source_type="payment").delete()

    entry = post_payment(payment)
    lines = list(entry.lines.all())
    assert sum(line.debit for line in lines) == sum(line.credit for line in lines)
    credit_codes = [line.account.code for line in lines if line.credit > 0]
    assert "4200" in credit_codes


@pytest.mark.django_db
def test_deposit_payment_balances(residential_tenant):
    from apps.ledger.models import JournalEntry
    from apps.ledger.posting import post_payment
    from apps.payments.models import PaymentType

    JournalEntry.objects.filter(source_type="payment").delete()
    payment = _make_payment(residential_tenant, "25000.00", PaymentType.DEPOSIT)
    JournalEntry.objects.filter(source_type="payment").delete()

    entry = post_payment(payment)
    lines = list(entry.lines.all())
    assert sum(line.debit for line in lines) == sum(line.credit for line in lines)
    debit_codes = [line.account.code for line in lines if line.debit > 0]
    credit_codes = [line.account.code for line in lines if line.credit > 0]
    assert "1030" in debit_codes
    assert "2100" in credit_codes


@pytest.mark.django_db
def test_post_expense_bank_balances(expense_category, building):
    from apps.ledger.models import JournalEntry
    from apps.ledger.posting import post_expense

    JournalEntry.objects.filter(source_type="expense").delete()
    expense = _make_expense(expense_category, "5000.00", building=building, method="bank")
    JournalEntry.objects.filter(source_type="expense").delete()

    entry = post_expense(expense)
    lines = list(entry.lines.all())
    assert sum(line.debit for line in lines) == sum(line.credit for line in lines)
    credit_codes = [line.account.code for line in lines if line.credit > 0]
    assert "1020" in credit_codes, "Bank expense should credit 1020"


@pytest.mark.django_db
def test_post_expense_petty_cash_credits_1010(expense_category, building):
    from apps.ledger.models import JournalEntry
    from apps.ledger.posting import post_expense

    JournalEntry.objects.filter(source_type="expense").delete()
    expense = _make_expense(expense_category, "500.00", building=building, method="petty_cash")
    JournalEntry.objects.filter(source_type="expense").delete()

    entry = post_expense(expense)
    lines = list(entry.lines.all())
    assert sum(line.debit for line in lines) == sum(line.credit for line in lines)
    credit_codes = [line.account.code for line in lines if line.credit > 0]
    assert "1010" in credit_codes, f"Petty cash expense should credit 1010, got {credit_codes}"
    assert "1020" not in credit_codes, "Petty cash expense must NOT credit 1020"


# ── reversal nets to zero ─────────────────────────────────────────────────────

@pytest.mark.django_db
def test_payment_reversal_nets_to_zero(residential_tenant):
    from django.db.models import Sum

    from apps.ledger.models import JournalEntry, JournalLine
    from apps.ledger.posting import post_payment, reverse_payment
    from apps.payments.models import PaymentType

    JournalEntry.objects.filter(source_type="payment").delete()
    payment = _make_payment(residential_tenant, "25000.00", PaymentType.RENT)
    JournalEntry.objects.filter(source_type="payment").delete()

    post_payment(payment)
    reverse_payment(payment)

    # Net debit and credit for 1020 across both entries should cancel
    agg = JournalLine.objects.filter(
        entry__source_type="payment",
        entry__source_id=payment.pk,
        account__code="1020",
    ).aggregate(d=Sum("debit"), c=Sum("credit"))
    net = (agg["d"] or Decimal("0")) - (agg["c"] or Decimal("0"))
    assert net == Decimal("0"), f"1020 should net to zero after reversal, got {net}"


@pytest.mark.django_db
def test_expense_reversal_nets_to_zero(expense_category, building):
    from django.db.models import Sum

    from apps.ledger.models import JournalEntry, JournalLine
    from apps.ledger.posting import post_expense, reverse_expense

    JournalEntry.objects.filter(source_type="expense").delete()
    expense = _make_expense(expense_category, "3000.00", building=building)
    JournalEntry.objects.filter(source_type="expense").delete()

    post_expense(expense)
    reverse_expense(expense)

    agg = JournalLine.objects.filter(
        entry__source_type="expense",
        entry__source_id=expense.pk,
        account__code=expense_category.account.code,
    ).aggregate(d=Sum("debit"), c=Sum("credit"))
    net = (agg["d"] or Decimal("0")) - (agg["c"] or Decimal("0"))
    assert net == Decimal("0"), f"Expense account should net to zero after reversal, got {net}"


# ── idempotency ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_posting_same_payment_twice_creates_one_entry(residential_tenant):
    from apps.ledger.models import JournalEntry
    from apps.ledger.posting import post_payment
    from apps.payments.models import PaymentType

    JournalEntry.objects.filter(source_type="payment").delete()
    payment = _make_payment(residential_tenant, "25000.00", PaymentType.RENT)
    JournalEntry.objects.filter(source_type="payment").delete()

    post_payment(payment)
    post_payment(payment)  # Second call — must be idempotent

    count = JournalEntry.objects.filter(
        source_type="payment", source_id=payment.pk, kind="normal"
    ).count()
    assert count == 1, f"Expected 1 entry, got {count}"


@pytest.mark.django_db
def test_posting_same_expense_twice_creates_one_entry(expense_category, building):
    from apps.ledger.models import JournalEntry
    from apps.ledger.posting import post_expense

    JournalEntry.objects.filter(source_type="expense").delete()
    expense = _make_expense(expense_category, "1000.00", building=building)
    JournalEntry.objects.filter(source_type="expense").delete()

    post_expense(expense)
    post_expense(expense)

    count = JournalEntry.objects.filter(
        source_type="expense", source_id=expense.pk, kind="normal"
    ).count()
    assert count == 1, f"Expected 1 entry, got {count}"


# ── trial balance ─────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_trial_balance_balanced_after_multiple_postings(residential_tenant, commercial_tenant, expense_category, building):
    from django.db.models import Sum

    from apps.ledger.models import JournalEntry, JournalLine
    from apps.ledger.posting import post_expense, post_payment
    from apps.payments.models import PaymentType

    JournalEntry.objects.all().delete()

    p1 = _make_payment(residential_tenant, "25000.00", PaymentType.RENT)
    p2 = _make_payment(commercial_tenant, "50000.00", PaymentType.RENT)
    p3 = _make_payment(residential_tenant, "1000.00", PaymentType.LATE_FEE)
    e1 = _make_expense(expense_category, "5000.00", building=building)

    JournalEntry.objects.all().delete()

    for p in [p1, p2, p3]:
        post_payment(p)
    post_expense(e1)

    agg = JournalLine.objects.aggregate(d=Sum("debit"), c=Sum("credit"))
    total_debit = agg["d"] or Decimal("0")
    total_credit = agg["c"] or Decimal("0")
    assert total_debit == total_credit, (
        f"Trial balance not balanced: DR={total_debit} CR={total_credit}"
    )


# ── balance sheet ─────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_balance_sheet_assets_equal_liabilities_plus_equity(
    residential_tenant, expense_category, building
):
    from apps.ledger.models import JournalEntry
    from apps.ledger.posting import post_expense, post_payment
    from apps.payments.models import PaymentType

    JournalEntry.objects.all().delete()

    p = _make_payment(residential_tenant, "25000.00", PaymentType.RENT)
    e = _make_expense(expense_category, "3000.00", building=building)

    JournalEntry.objects.all().delete()
    post_payment(p)
    post_expense(e)

    # Use the view helper
    from apps.dashboard.views_reports import AccountingDashboardView
    view = AccountingDashboardView()
    result = view._tab_balance_sheet(4, 2026)

    total_assets = sum(result["assets"].values())
    total_liabilities = sum(result["liabilities"].values())
    equity = result["equity"]

    assert abs(total_assets - (total_liabilities + equity)) < 0.01, (
        f"Balance sheet not balanced: assets={total_assets} "
        f"liabilities={total_liabilities} equity={equity}"
    )
