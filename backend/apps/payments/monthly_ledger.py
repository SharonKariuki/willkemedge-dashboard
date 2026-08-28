"""Month-by-month rent roll for one tenant.

Mirrors the columns the landlord keeps in the rent-roll spreadsheet:

    Arrears B/F | <Month> Rent | Other charges | Total due | Payment made | Balance

One row per calendar month, from the tenant's first billed (or paid) period
through the current month. The rows are derived from stored records only —
``Arrears`` for the monthly charge, ``UtilityCharge`` for other charges and
``Payment`` for cash received — so the table extends itself when the monthly
billing task posts the next period. Nothing to regenerate by hand.

Roll-forward, per month:

    balance = arrears_b/f + rent + VAT + other charges - payments - waivers

and that balance becomes the next month's arrears b/f. A prepayment leaves the
balance negative, which is exactly the credit the tenant carries into the next
month, so ``Arrears.credit_applied`` is deliberately NOT added again here — it
is already expressed by the negative carry.

Public API
----------
build_monthly_ledger(tenant, *, months=24, today=None) -> list[dict]
"""
from __future__ import annotations

import datetime as _dt
from decimal import Decimal

ZERO = Decimal("0.00")

#  Written into ``Arrears.waive_notes`` by the statement-seeding commands. It is
#  how a carried opening balance is told apart from a month that was genuinely
#  billed, since both are stored as an Arrears row.
OPENING_MARKER = "Opening position carried"

#  Most recent N months returned. The roll-forward is computed over the tenant's
#  whole history first, so the oldest row shown still carries a correct b/f.
DEFAULT_MONTHS = 24


def _money(value) -> Decimal:
    return (Decimal(value) if value is not None else ZERO).quantize(Decimal("0.01"))


def _key(year: int, month: int) -> int:
    return year * 12 + (month - 1)


def _from_key(key: int) -> tuple[int, int]:
    return key // 12, key % 12 + 1


def _label(year: int, month: int) -> str:
    try:
        return _dt.date(year, month, 1).strftime("%B %Y")
    except ValueError:  # pragma: no cover - guarded by the model's constraint
        return f"{month}/{year}"


def build_monthly_ledger(tenant, *, months: int = DEFAULT_MONTHS, today: _dt.date | None = None) -> list[dict]:
    """Return the tenant's rent roll, oldest month first."""
    from .models import Arrears, Payment, PaymentType, UtilityCharge

    today = today or _dt.date.today()

    charges: dict[int, Arrears] = {}
    for arr in Arrears.objects.filter(tenant=tenant):
        charges[_key(arr.period_year, arr.period_month)] = arr

    other: dict[int, Decimal] = {}
    for util in UtilityCharge.objects.filter(tenant=tenant):
        k = _key(util.period_year, util.period_month)
        other[k] = other.get(k, ZERO) + _money(util.amount)

    # Deposits are a refundable liability, not rent paid — the same exclusion the
    # statement ledger makes. Voided payments never really arrived.
    paid: dict[int, Decimal] = {}
    payments = (
        Payment.objects.filter(tenant=tenant, voided_at__isnull=True)
        .exclude(payment_type=PaymentType.DEPOSIT)
        .only("amount", "period_month", "period_year")
    )
    for pay in payments:
        k = _key(pay.period_year, pay.period_month)
        paid[k] = paid.get(k, ZERO) + _money(pay.amount)

    keys = set(charges) | set(other) | set(paid)
    if not keys:
        return []

    # Run to the current month even when billing has not posted yet, so the row
    # for "this month" exists and shows what is still owed.
    start, end = min(keys), max(max(keys), _key(today.year, today.month))

    rows: list[dict] = []
    balance = ZERO
    for k in range(start, end + 1):
        year, month = _from_key(k)
        arr = charges.get(k)
        brought_forward = balance
        rent = _money(arr.expected_rent) if arr else ZERO
        vat = _money(arr.expected_vat) if arr else ZERO
        waived = _money(arr.waived_amount) if arr else ZERO
        other_charges = other.get(k, ZERO)
        received = paid.get(k, ZERO)

        # An opening row carries a balance brought forward from before the books
        # began, not a month's rent. It is stored as a charge because that is
        # the only way to seed the roll-forward, but reporting it under "rent"
        # reads as though the month was billed that amount — Elimisha's July
        # showed "Rent 20,000" against an actual rent of 22,500. Move it to the
        # column it belongs in. The total is unchanged either way, so the
        # roll-forward into the next month is untouched.
        is_opening = bool(arr and OPENING_MARKER in (arr.waive_notes or ""))
        if is_opening:
            brought_forward += rent
            rent = ZERO

        total_due = brought_forward + rent + vat + other_charges
        balance = total_due - received - waived
        rows.append({
            "period": f"{month}/{year}",
            "period_month": month,
            "period_year": year,
            "label": _label(year, month),
            "brought_forward": str(brought_forward),
            "rent": str(rent),
            "vat": str(vat),
            "other_charges": str(other_charges),
            "waived": str(waived),
            "total_due": str(total_due),
            "paid": str(received),
            "balance": str(balance),
            "is_opening": is_opening,
        })

    return rows[-months:] if months and months > 0 else rows
