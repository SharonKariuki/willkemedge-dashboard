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


def _make_expense(category, amount, building=None, method="bank", unit=None):
    from apps.expenses.models import Expense
    e = Expense(
        date=datetime.date(2026, 4, 15),
        category=category,
        amount=Decimal(str(amount)),
        description="Test expense",
        period_month=4,
        period_year=2026,
        building=building,
        unit=unit,
        payment_method=method,
    )
    e.save()
    return e


@pytest.mark.django_db
def test_unit_scoped_expense_names_the_unit_in_the_ledger(expense_category, residential_unit):
    """A JournalEntry has no unit column, so the unit rides in the text.

    Without it a GL row for a unit-level repair is indistinguishable from a
    building-wide one once it leaves the expenses table.
    """
    from apps.ledger import posting

    expense = _make_expense(
        expense_category, "4000", building=residential_unit.building, unit=residential_unit,
    )
    entry = posting.post_expense(expense, replace=True)

    tag = f"[Unit {residential_unit.label}]"
    assert tag in entry.memo
    debit_line = entry.lines.get(debit__gt=0)
    assert tag in debit_line.description


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


def _legs(entry):
    return sorted(
        (line.account.code, line.debit, line.credit) for line in entry.lines.all()
    )


@pytest.mark.django_db
@pytest.mark.parametrize("tenant_fixture", ["residential_tenant", "commercial_tenant"])
def test_rent_receipt_settles_the_tenant_account(tenant_fixture, request):
    """Accrual: the rent was income when billed, so cash only clears 1040 —
    for a commercial tenant too (its VAT went to 2600 on the invoice)."""
    from apps.ledger.models import JournalEntry
    from apps.ledger.posting import post_payment
    from apps.payments.models import PaymentType

    tenant = request.getfixturevalue(tenant_fixture)
    payment = _make_payment(tenant, "58000.00", PaymentType.RENT)
    JournalEntry.objects.filter(source_type="payment").delete()

    entry = post_payment(payment)
    assert _legs(entry) == [
        ("1020", Decimal("58000.00"), Decimal("0.00")),
        ("1040", Decimal("0.00"), Decimal("58000.00")),
    ]


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
    # The statement counts it as a receipt against the account; the books agree.
    credit_codes = [line.account.code for line in lines if line.credit > 0]
    assert credit_codes == ["1040"]


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

    import datetime as _dt

    from apps.ledger.reports import balance_sheet

    result = balance_sheet(_dt.date(2026, 4, 30))

    assert result["balanced"], (
        f"Balance sheet not balanced: assets={result['total_assets']} "
        f"liabilities={result['total_liabilities']} equity={result['total_equity']}"
    )


def _bill(tenant, month, rent, *, vat="0", waived="0", notes=""):
    from apps.payments.models import Arrears

    return Arrears.objects.create(
        tenant=tenant, period_month=month, period_year=2026,
        expected_rent=Decimal(rent), expected_vat=Decimal(vat),
        waived_amount=Decimal(waived), waive_notes=notes,
        amount_paid=Decimal("0"), balance=Decimal(rent) + Decimal(vat) - Decimal(waived),
    )


def _arrear_entry(arrear, kind="normal"):
    from apps.ledger.models import JournalEntry

    return JournalEntry.objects.get(source_type="arrear", source_id=arrear.pk, kind=kind)


@pytest.mark.django_db
def test_billing_rent_posts_the_receivable_and_income(residential_tenant):
    """Accrual: a month's rent is income in the month it bills."""
    arrear = _bill(residential_tenant, 4, "25000.00")
    entry = _arrear_entry(arrear)
    assert entry.date == datetime.date(2026, 4, 1)
    assert _legs(entry) == [
        ("1040", Decimal("25000.00"), Decimal("0.00")),
        ("4110", Decimal("0.00"), Decimal("25000.00")),
    ]


@pytest.mark.django_db
def test_commercial_rent_bills_vat_to_2600(commercial_tenant):
    arrear = _bill(commercial_tenant, 4, "50000.00", vat="8000.00")
    assert _legs(_arrear_entry(arrear)) == [
        ("1040", Decimal("58000.00"), Decimal("0.00")),
        ("2600", Decimal("0.00"), Decimal("8000.00")),
        ("4120", Decimal("0.00"), Decimal("50000.00")),
    ]


@pytest.mark.django_db
def test_a_waiver_gives_back_income_and_its_vat(commercial_tenant):
    arrear = _bill(commercial_tenant, 4, "50000.00", vat="8000.00", waived="5800.00")
    net = {}
    for code, d, c in _legs(_arrear_entry(arrear)):
        net[code] = net.get(code, Decimal("0")) + d - c
    assert net == {
        "1040": Decimal("52200.00"),
        "2600": Decimal("-7200.00"),
        "4120": Decimal("-45000.00"),
    }


@pytest.mark.django_db
def test_editing_a_charge_reposts_and_deleting_reverses(residential_tenant):
    from apps.ledger.models import JournalLine

    arrear = _bill(residential_tenant, 4, "25000.00")
    arrear.expected_rent = Decimal("20000.00")
    arrear.save()
    assert ("4110", Decimal("0.00"), Decimal("20000.00")) in _legs(_arrear_entry(arrear))

    pk = arrear.pk
    arrear.delete()
    net = sum(
        (ln.debit - ln.credit for ln in JournalLine.objects.filter(
            entry__source_type="arrear", entry__source_id=pk, account__code="1040")),
        Decimal("0"),
    )
    assert net == Decimal("0")


@pytest.mark.django_db
def test_a_rent_free_month_posts_nothing(residential_tenant):
    from apps.ledger.models import JournalEntry

    arrear = _bill(residential_tenant, 4, "0")
    assert not JournalEntry.objects.filter(source_type="arrear", source_id=arrear.pk).exists()


@pytest.mark.django_db
def test_opening_position_goes_to_equity_not_income(residential_tenant):
    """The balance carried in when the books began is not this month's rent,
    and nor is any row from before it (the go-live load's June rows)."""
    from apps.payments.monthly_ledger import OPENING_MARKER

    june = _bill(residential_tenant, 6, "35200.00")
    assert ("4110", Decimal("0.00"), Decimal("35200.00")) in _legs(_arrear_entry(june))

    july = _bill(residential_tenant, 7, "28850.00", notes=f"{OPENING_MARKER} from the sheet.")
    assert _legs(_arrear_entry(july)) == [
        ("1040", Decimal("28850.00"), Decimal("0.00")),
        ("3300", Decimal("0.00"), Decimal("28850.00")),
    ]
    # Saving the opening row re-posts the earlier one as opening equity too.
    assert _legs(_arrear_entry(june)) == [
        ("1040", Decimal("35200.00"), Decimal("0.00")),
        ("3300", Decimal("0.00"), Decimal("35200.00")),
    ]
