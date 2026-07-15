"""
Posting service — pure functions that build balanced double-entry journal entries.

Every public function returns a saved JournalEntry with balanced JournalLines.
The idempotency UniqueConstraint on (source_type, source_id, kind) ensures
that re-running posting for the same Payment/Expense never creates duplicates.

GL account codes used
─────────────────────
Assets (debit-normal):
  1010  Petty Cash
  1020  Operating Bank Account
  1030  Tenant Security Deposit Bank Account
  1040  Accounts Receivable (Rent Arrears)

Liabilities (credit-normal):
  2100  Tenant Security Deposits Held
  2600  VAT Payable — 16% on COMMERCIAL rent only (see _split_vat)

Income (credit-normal):
  4110  Residential Rental Income
  4120  Commercial Rental Income
  4150  Service Charge / Utilities Reimbursed
  4200  Late Payment Fees / Penalties
  4250  Parking / Miscellaneous Income

Expenses (debit-normal):
  5xxx / 6xxx  — from expense.category.account
"""
import datetime
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.dateparse import parse_date

from apps.buildings.models import UnitClassification
from apps.expenses.coa import RENT_RECEIVABLE, SERVICE_CHARGE_UTILITIES
from apps.expenses.coa import (
    RENT_COMMERCIAL,
    RENT_RECEIVABLE,
    RENT_RESIDENTIAL,
    VAT_PAYABLE,
)
from apps.expenses.models import Account
from apps.payments.models import PaymentType
from apps.payments.tax_service import TAX_RATE_BUSINESS, calculate_tax

from .models import JournalEntry, JournalLine

# ── helpers ────────────────────────────────────────────────────────────────

def _get_account(code: str) -> Account:
    try:
        return Account.objects.get(code=code, is_header=False)
    except Account.DoesNotExist:
        raise ValueError(f"GL account {code!r} not found in Chart of Accounts.") from None


def _as_date(value) -> datetime.date:
    """
    Coerce a source row's date into a ``datetime.date``.

    Newly-created Payment/Expense instances still hold whatever was assigned to
    the date field — often an ISO string (e.g. ``process_payment`` and the IPN
    importer pass ``"2026-04-05"``). Django only casts to ``date`` on reload, so
    the post_save signal sees the raw string. Normalise here so period
    derivation never blows up.
    """
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    parsed = parse_date(str(value))
    if parsed is None:
        raise ValueError(f"Unparseable journal entry date: {value!r}")
    return parsed


def _build_entry(
    *,
    date,
    memo: str,
    reference: str = "",
    building=None,
    source_type: str,
    source_id: int,
    kind: str = "normal",
    lines: list,  # list of (account_code, debit, credit, description)
) -> JournalEntry:
    """
    Atomically create a JournalEntry + its JournalLines.
    Raises ValidationError if lines don't balance.
    Uses update_or_create on the unique constraint so calling twice is safe.
    """
    date = _as_date(date)
    # Drop no-op lines (e.g. a zero VAT leg on a zero-rated commercial charge).
    lines = [
        ln for ln in lines
        if Decimal(str(ln[1])) != Decimal("0") or Decimal(str(ln[2])) != Decimal("0")
    ]
    total_debit = sum(Decimal(str(d)) for _, d, _, _ in lines)
    total_credit = sum(Decimal(str(c)) for _, _, c, _ in lines)
    if total_debit != total_credit:
        raise ValidationError(
            f"Entry for {source_type}#{source_id} does not balance: "
            f"DR={total_debit} CR={total_credit}"
        )

    with transaction.atomic():
        entry, created = JournalEntry.objects.update_or_create(
            source_type=source_type,
            source_id=source_id,
            kind=kind,
            defaults={
                "date": date,
                "memo": memo,
                "reference": reference,
                "building": building,
                "is_posted": True,
            },
        )
        if not created:
            # Already posted — idempotent, just return the existing entry
            return entry

        # Set period from date
        entry.period_month = date.month
        entry.period_year = date.year
        entry.save(update_fields=["period_month", "period_year"])

        for code, debit, credit, description in lines:
            account = _get_account(code)
            JournalLine.objects.create(
                entry=entry,
                account=account,
                debit=Decimal(str(debit)),
                credit=Decimal(str(credit)),
                description=description,
            )

    return entry


def _classification_of(tenant) -> str:
    try:
        return tenant.unit.classification
    except AttributeError:
        return UnitClassification.RESIDENTIAL


def _income_account_for_payment(payment) -> str:
    """Return 4110 or 4120 based on unit classification."""
    if _classification_of(payment.tenant) == UnitClassification.BUSINESS:
        return RENT_COMMERCIAL
    return RENT_RESIDENTIAL


def _split_vat_inclusive(gross: Decimal) -> tuple[Decimal, Decimal]:
    """Extract 16% VAT from a VAT-INCLUSIVE amount (cash actually received).

    A commercial tenant pays rent + 16% VAT as one figure, so a receipt of
    KES 27,840 is KES 24,000 income and KES 3,840 VAT owed to KRA.
    Returns (net, vat); net + vat == gross exactly (VAT absorbs the rounding).
    """
    net = (gross / (Decimal("1") + TAX_RATE_BUSINESS)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return net, gross - net


def _split_vat_exclusive(net: Decimal) -> tuple[Decimal, Decimal]:
    """Add 16% VAT to a VAT-EXCLUSIVE base amount (rent as billed).

    Unit.monthly_rent / Arrears.expected_rent hold the BASE rent for commercial
    units (see import_matasia), so billing adds VAT on top.
    Returns (net, vat).
    """
    return net, calculate_tax(net, UnitClassification.BUSINESS).tax_amount if net > 0 else Decimal("0")


# ── Payment posting ─────────────────────────────────────────────────────────

def post_payment(payment) -> JournalEntry:
    """
    Post a single Payment to the ledger.

    RENT        → DR 1020 / CR 4110 or 4120 (by classification)
    LATE_FEE    → DR 1020 / CR 4200
    DEPOSIT     → DR 1030 / CR 2100
    OTHER       → DR 1020 / CR 4150 (or 4250 for parking notes)
    """
    amt = payment.amount
    ptype = payment.payment_type
    date = payment.payment_date
    building = getattr(payment.tenant.unit, "building", None) if payment.tenant_id else None

    if ptype == PaymentType.RENT:
        income_code = _income_account_for_payment(payment)
        if income_code == RENT_COMMERCIAL:
            # Commercial rent is received VAT-inclusive: split the 16% out to
            # 2600 VAT Payable so only the net is recognised as income.
            net, vat = _split_vat_inclusive(amt)
            lines = [
                ("1020", amt, Decimal("0"), f"Rent collected — {payment.tenant}"),
                (income_code, Decimal("0"), net, "Commercial Rental Income"),
                (VAT_PAYABLE, Decimal("0"), vat, "16% VAT on commercial rent"),
            ]
        else:
            lines = [
                ("1020", amt, Decimal("0"), f"Rent collected — {payment.tenant}"),
                (income_code, Decimal("0"), amt, "Residential Rental Income"),
            ]
        memo = f"Rent collected: {payment.tenant} {payment.period_month}/{payment.period_year}"

    elif ptype == PaymentType.LATE_FEE:
        lines = [
            ("1020", amt, Decimal("0"), f"Late fee — {payment.tenant}"),
            ("4200", Decimal("0"), amt, "Late Payment Fees / Penalties"),
        ]
        memo = f"Late fee: {payment.tenant} {payment.period_month}/{payment.period_year}"

    elif ptype == PaymentType.DEPOSIT:
        lines = [
            ("1030", amt, Decimal("0"), f"Deposit received — {payment.tenant}"),
            ("2100", Decimal("0"), amt, "Tenant Security Deposits Held"),
        ]
        memo = f"Security deposit: {payment.tenant}"

    else:  # OTHER
        notes = (getattr(payment, "notes", "") or "").lower()
        income_code = "4250" if "parking" in notes else "4150"
        lines = [
            ("1020", amt, Decimal("0"), f"Other income — {payment.tenant}"),
            (income_code, Decimal("0"), amt, "Other Income"),
        ]
        memo = f"Other income: {payment.tenant} {payment.period_month}/{payment.period_year}"

    return _build_entry(
        date=date,
        memo=memo,
        reference=payment.reference,
        building=building,
        source_type="payment",
        source_id=payment.pk,
        kind="normal",
        lines=lines,
    )


def reverse_payment(payment) -> JournalEntry:
    """
    Create a reversal entry (mirror-image) for a Payment.
    The original entry is kept for audit; this adds a separate REVERSAL entry.
    """
    amt = payment.amount
    ptype = payment.payment_type
    date = payment.payment_date
    building = getattr(payment.tenant.unit, "building", None) if payment.tenant_id else None

    if ptype == PaymentType.RENT:
        income_code = _income_account_for_payment(payment)
        if income_code == RENT_COMMERCIAL:
            net, vat = _split_vat_inclusive(amt)
            lines = [
                ("1020", Decimal("0"), amt, f"REVERSAL — rent — {payment.tenant}"),
                (income_code, net, Decimal("0"), "REVERSAL — commercial rental income"),
                (VAT_PAYABLE, vat, Decimal("0"), "REVERSAL — 16% VAT on commercial rent"),
            ]
        else:
            lines = [
                ("1020", Decimal("0"), amt, f"REVERSAL — rent — {payment.tenant}"),
                (income_code, amt, Decimal("0"), "REVERSAL — rental income"),
            ]
    elif ptype == PaymentType.LATE_FEE:
        lines = [
            ("1020", Decimal("0"), amt, f"REVERSAL — late fee — {payment.tenant}"),
            ("4200", amt, Decimal("0"), "REVERSAL — late fees"),
        ]
    elif ptype == PaymentType.DEPOSIT:
        lines = [
            ("1030", Decimal("0"), amt, f"REVERSAL — deposit — {payment.tenant}"),
            ("2100", amt, Decimal("0"), "REVERSAL — deposits held"),
        ]
    else:
        notes = (getattr(payment, "notes", "") or "").lower()
        income_code = "4250" if "parking" in notes else "4150"
        lines = [
            ("1020", Decimal("0"), amt, f"REVERSAL — other income — {payment.tenant}"),
            (income_code, amt, Decimal("0"), "REVERSAL — other income"),
        ]

    return _build_entry(
        date=date,
        memo=f"REVERSAL: {payment}",
        reference=payment.reference,
        building=building,
        source_type="payment",
        source_id=payment.pk,
        kind="reversal",
        lines=lines,
    )


# ── Expense posting ─────────────────────────────────────────────────────────

def _expense_payment_method(expense) -> str:
    """Return the payment method for an expense — 'bank' or 'petty_cash'."""
    return getattr(expense, "payment_method", "bank") or "bank"


def post_expense(expense) -> JournalEntry:
    """
    Post an Expense to the ledger.

    bank        → DR 5xxx/6xxx / CR 1020
    petty_cash  → DR 5xxx/6xxx / CR 1010
    """
    if not expense.category_id or not expense.category.account_id:
        raise ValueError(
            f"Expense #{expense.pk} has no GL account mapped via its category."
        )

    expense_account_code = expense.category.account.code
    amt = expense.amount
    method = _expense_payment_method(expense)
    credit_account = "1010" if method == "petty_cash" else "1020"
    credit_desc = "Petty Cash" if method == "petty_cash" else "Operating Bank Account"

    lines = [
        (expense_account_code, amt, Decimal("0"), expense.description or expense.category.name),
        (credit_account, Decimal("0"), amt, credit_desc),
    ]
    memo = f"Expense: {expense.category.name} — {expense.description or ''}"

    return _build_entry(
        date=expense.date,
        memo=memo[:255],
        reference=expense.reference,
        building=expense.building,
        source_type="expense",
        source_id=expense.pk,
        kind="normal",
        lines=lines,
    )


def reverse_expense(expense) -> JournalEntry:
    """Create a reversal entry (mirror-image) for an Expense."""
    if not expense.category_id or not expense.category.account_id:
        raise ValueError(
            f"Expense #{expense.pk} has no GL account mapped via its category."
        )

    expense_account_code = expense.category.account.code
    amt = expense.amount
    method = _expense_payment_method(expense)
    debit_account = "1010" if method == "petty_cash" else "1020"

    lines = [
        (expense_account_code, Decimal("0"), amt, f"REVERSAL — {expense.category.name}"),
        (debit_account, amt, Decimal("0"), "REVERSAL — cash refund"),
    ]

    return _build_entry(
        date=expense.date,
        memo=f"REVERSAL: {expense.category.name} — {expense.description or ''}",
        reference=expense.reference,
        building=expense.building,
        source_type="expense",
        source_id=expense.pk,
        kind="reversal",
        lines=lines,
    )


# ── Arrears posting ─────────────────────────────────────────────────────────

def post_arrear(arrear) -> JournalEntry:
    """
    Post a rent-billed-but-unpaid Arrears record.

    DR 1040 Accounts Receivable / CR 4110 or 4120
    """
    classification = _classification_of(arrear.tenant)
    amt = arrear.balance
    building = getattr(arrear.tenant.unit, "building", None)

    if classification == UnitClassification.BUSINESS:
        # Billed commercial rent is held VAT-exclusive, so the tenant owes
        # rent + 16%: raise the receivable at gross and credit VAT to 2600.
        net, vat = _split_vat_exclusive(amt)
        lines = [
            (RENT_RECEIVABLE, net + vat, Decimal("0"), f"Rent billed — {arrear.tenant}"),
            (RENT_COMMERCIAL, Decimal("0"), net, "Commercial Rental Income (billed)"),
            (VAT_PAYABLE, Decimal("0"), vat, "16% VAT on commercial rent (billed)"),
        ]
    else:
        lines = [
            (RENT_RECEIVABLE, amt, Decimal("0"), f"Rent billed — {arrear.tenant}"),
            (RENT_RESIDENTIAL, Decimal("0"), amt, "Rental Income (billed)"),
        ]

    return _build_entry(
        date=_period_to_date(arrear.period_month, arrear.period_year),
        memo=f"Rent billed: {arrear.tenant} {arrear.period_month}/{arrear.period_year}",
        building=building,
        source_type="arrear",
        source_id=arrear.pk,
        kind="normal",
        lines=lines,
    )


def post_utility_charge(charge) -> JournalEntry:
    """
    Post a water/utility charge billed to a tenant.

    DR 1040 Accounts Receivable / CR 4150 Service Charge — Utilities Reimbursed

    Utility charges appeared on the tenant statement as "Other Charges" but were
    never posted to the general ledger, so recovered utility income was missing
    from the books entirely.
    """
    amt = charge.amount
    building = getattr(charge.tenant.unit, "building", None)

    lines = [
        (RENT_RECEIVABLE, amt, Decimal("0"), f"{charge.label} billed — {charge.tenant}"),
        (SERVICE_CHARGE_UTILITIES, Decimal("0"), amt, "Service Charge / Utilities Reimbursed"),
    ]

    return _build_entry(
        date=charge.posting_date,
        memo=f"{charge.label}: {charge.tenant} {charge.period_month}/{charge.period_year}",
        building=building,
        source_type="utility_charge",
        source_id=charge.pk,
        kind="normal",
        lines=lines,
    )


def post_petty_cash_topup(payment) -> JournalEntry:
    """
    Post a petty-cash top-up: DR 1010 Petty Cash / CR 1020 Operating Bank.
    Source is treated as a special payment of type OTHER with notes='petty_cash_topup'.
    """
    amt = payment.amount
    lines = [
        ("1010", amt, Decimal("0"), "Petty cash top-up"),
        ("1020", Decimal("0"), amt, "Transfer from operating bank"),
    ]
    return _build_entry(
        date=payment.payment_date,
        memo=f"Petty cash top-up — {payment.reference or ''}",
        reference=payment.reference,
        building=None,
        source_type="petty_topup",
        source_id=payment.pk,
        kind="normal",
        lines=lines,
    )


def post_deposit_refund(payment) -> JournalEntry:
    """
    Post a deposit refund: DR 2100 Deposits Held / CR 1030 Deposit Bank.
    """
    amt = payment.amount
    lines = [
        ("2100", amt, Decimal("0"), f"Deposit refunded — {payment.tenant}"),
        ("1030", Decimal("0"), amt, "Tenant Security Deposit Bank"),
    ]
    return _build_entry(
        date=payment.payment_date,
        memo=f"Deposit refund: {payment.tenant}",
        reference=payment.reference,
        building=None,
        source_type="deposit_refund",
        source_id=payment.pk,
        kind="normal",
        lines=lines,
    )


# ── Opening balances (data migration) ────────────────────────────────────────

def post_opening_balances(tenant, *, net_balance, deposit, date, equity_code="3300"):
    """Post a tenant's OPENING position when migrating their books into the ledger.

    Used by the initial property-data load — NOT for ongoing activity.

    Security deposit already held  → DR 1030 / CR 2100  (balance-sheet only).
    Net arrears the tenant owes    → DR 1040 / CR <equity>  (opening equity,
                                     NOT current rental income — otherwise the
                                     cutover month's P&L is overstated by every
                                     brought-forward balance).
    Net credit (tenant overpaid)   → DR <equity> / CR 1040.

    Idempotent via the (source_type, source_id, kind) unique constraint:
    re-running for the same tenant updates rather than duplicates.
    Returns the list of JournalEntry objects created.
    """
    building = getattr(tenant.unit, "building", None) if tenant.unit_id else None
    deposit = Decimal(str(deposit or 0))
    net = Decimal(str(net_balance or 0))
    entries = []

    if deposit > 0:
        entries.append(_build_entry(
            date=date,
            memo=f"Opening security deposit held — {tenant}"[:255],
            building=building,
            source_type="opening_deposit",
            source_id=tenant.pk,
            lines=[
                ("1030", deposit, Decimal("0"), "Deposit bank (opening balance)"),
                ("2100", Decimal("0"), deposit, f"Deposit held — {tenant}"),
            ],
        ))

    if net > 0:
        entries.append(_build_entry(
            date=date,
            memo=f"Opening arrears — {tenant}"[:255],
            building=building,
            source_type="opening_ar",
            source_id=tenant.pk,
            lines=[
                ("1040", net, Decimal("0"), f"Opening receivable — {tenant}"),
                (equity_code, Decimal("0"), net, "Opening balance equity"),
            ],
        ))
    elif net < 0:
        credit = -net
        entries.append(_build_entry(
            date=date,
            memo=f"Opening credit (overpaid) — {tenant}"[:255],
            building=building,
            source_type="opening_ar",
            source_id=tenant.pk,
            lines=[
                (equity_code, credit, Decimal("0"), "Opening balance equity"),
                ("1040", Decimal("0"), credit, f"Opening credit — {tenant}"),
            ],
        ))

    return entries


# ── utility ─────────────────────────────────────────────────────────────────

def _period_to_date(month: int, year: int):
    import datetime
    return datetime.date(year, month, 1)
