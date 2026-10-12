"""Figures shared by more than one report, computed in one place.

Two reports that print the same number must get it from the same function, or
they drift: the P&L, the annual income summary, the expense breakdown, the
landlord statement and the dashboard income trend all say "income", and before
this module each summed it its own way — gross here, net of VAT there, farm
income in one and not the other.

Also holds the query-parameter parsing every report shares, so a bad ``month``
or ``building`` answers 400 with a reason instead of a 500.
"""
from __future__ import annotations

import calendar
import datetime as _dt
from decimal import Decimal

from django.db.models import Count, Q, Sum
from rest_framework.exceptions import ValidationError

from apps.payments.models import Payment, PaymentType

ZERO = Decimal("0.00")
_CENT = Decimal("0.01")

# Security deposits are a liability (refundable), not income — never count them
# toward rental income or collection. Late fees and other income legitimately
# are income, so we exclude only DEPOSIT rather than restrict to RENT.
# Voided payments are excluded everywhere: the money was unwound in the ledger,
# so leaving them in would overstate every income and collection figure.
INCOME_PAYMENT_FILTER = ~Q(payment_type=PaymentType.DEPOSIT) & Q(voided_at__isnull=True)

def money(value) -> Decimal:
    return (Decimal(value) if value is not None else ZERO).quantize(_CENT)


# ── query parameters ─────────────────────────────────────────────────────────

def int_param(request, name: str, default=None, *, lo=None, hi=None):
    raw = request.query_params.get(name)
    if raw in (None, ""):
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ValidationError({name: f"'{raw}' is not a whole number."}) from None
    if (lo is not None and value < lo) or (hi is not None and value > hi):
        raise ValidationError({name: f"{value} is out of range."})
    return value


def period_params(request, today: _dt.date) -> tuple[int, int]:
    """``(month, year)`` from ``?month=&year=``, defaulting to this month."""
    month = int_param(request, "month", today.month, lo=1, hi=12)
    year = int_param(request, "year", today.year, lo=2000, hi=2100)
    return month, year


def building_param(request) -> int | None:
    return int_param(request, "building", None, lo=1)


def month_end(year: int, month: int) -> _dt.date:
    return _dt.date(year, month, calendar.monthrange(year, month)[1])


def month_start(year: int, month: int) -> _dt.date:
    return _dt.date(year, month, 1)


def previous_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


# ── income ───────────────────────────────────────────────────────────────────

#: Income accounts with a line of their own; every other income account
#: (farm produce and the like) is listed by name under ``manual_income``.
_RENT_RESIDENTIAL, _RENT_COMMERCIAL, _LATE_FEES = "4110", "4120", "4200"
_OTHER_INCOME = ("4150", "4250")


def _ledger_period(month: int, year: int, building_id):
    """``{code: (account, debits, credits)}`` for the month, from the ledger."""
    from apps.expenses.models import Account
    from apps.ledger.models import JournalLine

    lines = JournalLine.objects.filter(
        entry__is_posted=True,
        entry__date__gte=month_start(year, month),
        entry__date__lte=month_end(year, month),
    )
    if building_id:
        lines = lines.filter(entry__building_id=building_id)
    accounts = {a.code: a for a in Account.objects.filter(is_header=False)}
    return {
        row["account__code"]: (accounts[row["account__code"]], money(row["dr"]), money(row["cr"]), row["n"])
        for row in lines.values("account__code").annotate(
            dr=Sum("debit"), cr=Sum("credit"), n=Count("entry", distinct=True)
        )
    }


def income_lines(month: int, year: int, *, building_id: int | None = None) -> dict:
    """Every component of a period's income, net of VAT, plus the memo figures.

    Read from the general ledger, so it is the same income the Accounting page
    reports: rent in the month it is billed, water and other charges, credit
    notes already netted into the account they reduce, farm and other manual
    income — never deposits, never VAT.

    Returns Decimals::

        residential_rent, commercial_rent, late_fees, other_income,
        manual_income  -> [(account name, amount), ...]  (farm produce etc.)
        credit_adjustment  (always 0: credits sit inside the accounts above)
        total
        vat_collected, deposits_received   (memo: not income)
    """
    from apps.expenses.models import AccountType

    period = _ledger_period(month, year, building_id)

    def income(code):
        _acct, dr, cr, _n = period.get(code, (None, ZERO, ZERO, 0))
        return cr - dr

    residential = income(_RENT_RESIDENTIAL)
    commercial = income(_RENT_COMMERCIAL)
    late_fees = income(_LATE_FEES)
    other = sum((income(c) for c in _OTHER_INCOME), ZERO)
    named = {_RENT_RESIDENTIAL, _RENT_COMMERCIAL, _LATE_FEES, *_OTHER_INCOME}
    manual_rows = [
        (acct.name, cr - dr)
        for code, (acct, dr, cr, _n) in sorted(period.items())
        if acct.account_type == AccountType.INCOME and code not in named and cr != dr
    ]
    total = residential + commercial + late_fees + other + sum((a for _, a in manual_rows), ZERO)

    deposits = Payment.objects.filter(
        voided_at__isnull=True, payment_type=PaymentType.DEPOSIT,
        payment_date__gte=month_start(year, month), payment_date__lte=month_end(year, month),
    )
    if building_id:
        deposits = deposits.filter(tenant__unit__building_id=building_id)
    return {
        "residential_rent": residential,
        "commercial_rent": commercial,
        "late_fees": late_fees,
        "other_income": other,
        "manual_income": manual_rows,
        "credit_adjustment": ZERO,
        "total": money(total),
        "vat_collected": income("2600"),
        "deposits_received": money(deposits.aggregate(t=Sum("amount"))["t"]),
    }


def income_total(month: int, year: int, *, building_id: int | None = None) -> Decimal:
    return income_lines(month, year, building_id=building_id)["total"]


def expense_by_category(month: int, year: int, *, building_id: int | None = None) -> list[dict]:
    """``[{category, total, count}]`` from the ledger, one row per expense account.

    Every expense category posts to exactly one account of the same name (the
    locked chart), and a cost a tenant paid for us posts there too.
    """
    from apps.expenses.models import AccountType

    rows = [
        {"category": acct.name, "total": dr - cr, "count": n}
        for _code, (acct, dr, cr, n) in _ledger_period(month, year, building_id).items()
        if acct.account_type == AccountType.EXPENSE and dr != cr
    ]
    return sorted(rows, key=lambda r: (-r["total"], r["category"]))


# ── rent roll for one month, many tenants ────────────────────────────────────

def month_balances(tenants, month: int, year: int) -> dict[int, dict]:
    """``{tenant_id: {...}}`` — each tenant's rent-roll row for one month.

    The same roll-forward the tenant statement prints, for many tenants in a
    handful of queries::

        balance = brought_forward + charged + refunds − paid − credits

    ``brought_forward`` is the balance the roll closed the previous month on
    (plus any opening position carried into this month — that is a balance
    from before the books began, not a charge); ``balance`` is the one
    ``current_balances`` reports as at the month's end, so the column agrees
    with the tenant list and the statement.
    """
    from apps.payments.credits import issued_credits, sent_refunds
    from apps.payments.models import Arrears, UtilityCharge
    from apps.payments.monthly_ledger import OPENING_MARKER, current_balances

    ids = [t.pk if hasattr(t, "pk") else int(t) for t in tenants]
    if not ids:
        return {}

    start, end = month_start(year, month), month_end(year, month)
    prev_year, prev_month = previous_month(year, month)
    brought = current_balances(ids, today=month_end(prev_year, prev_month))
    closing = current_balances(ids, today=end)

    rows = {
        tid: {
            "brought_forward": brought.get(tid, ZERO),
            "rent": ZERO, "vat": ZERO, "other_charges": ZERO,
            "paid": ZERO, "credits": ZERO, "refunds": ZERO,
            "balance": closing.get(tid, ZERO),
        }
        for tid in ids
    }

    for arr in Arrears.objects.filter(tenant_id__in=ids, period_month=month, period_year=year):
        row = rows[arr.tenant_id]
        charge = money(arr.expected_rent) + money(arr.expected_vat)
        waived = money(arr.waived_amount)
        if OPENING_MARKER in (arr.waive_notes or ""):
            row["brought_forward"] += charge - waived
            continue
        row["rent"] += money(arr.expected_rent)
        row["vat"] += money(arr.expected_vat)
        row["credits"] += waived

    for tid, amount in UtilityCharge.objects.filter(
        tenant_id__in=ids, period_month=month, period_year=year
    ).values_list("tenant_id", "amount"):
        rows[tid]["other_charges"] += money(amount)

    for tid, amount in (
        Payment.objects.filter(
            tenant_id__in=ids, voided_at__isnull=True,
            payment_date__gte=start, payment_date__lte=end,
        )
        .exclude(payment_type=PaymentType.DEPOSIT)
        .values_list("tenant_id", "amount")
    ):
        rows[tid]["paid"] += money(amount)

    for tid, amount in issued_credits(ids).filter(
        credit_date__gte=start, credit_date__lte=end
    ).values_list("tenant_id", "amount"):
        rows[tid]["credits"] += money(amount)
    for tid, amount in sent_refunds(ids).filter(
        sent_on__gte=start, sent_on__lte=end
    ).values_list("tenant_id", "amount"):
        rows[tid]["refunds"] += money(amount)

    for row in rows.values():
        row["charged"] = row["rent"] + row["vat"] + row["other_charges"] + row["refunds"]
        balance, paid = row["balance"], row["paid"]
        if balance < 0:
            row["status"] = "In credit"
        elif balance == 0:
            row["status"] = "Paid"
        elif paid > 0 or row["credits"] > 0:
            row["status"] = "Partial"
        else:
            row["status"] = "Unpaid"
    return rows


def month_rows(month: int, year: int, *, building_id: int | None = None):
    """``[(tenant, row)]`` for the tenants a monthly balance report lists.

    A tenancy that overlaps the month is listed even when square. One that
    does not (moved out earlier, not yet moved in) is listed only while money
    is still moving or owed, so a former tenant's unpaid balance is not lost
    from the month's outstanding total. A rent-free occupancy with nothing on
    it is left out: a caretaker's row of zeros says nothing.
    """
    from apps.tenants.models import Tenant

    qs = Tenant.objects.select_related("unit", "unit__building")
    if building_id:
        qs = qs.filter(unit__building_id=building_id)
    tenants = list(qs.order_by("unit__building__name", "unit__label", "move_in_date"))
    balances = month_balances(tenants, month, year)

    start, end = month_start(year, month), month_end(year, month)
    listed = []
    for tenant in tenants:
        row = balances[tenant.pk]
        moving = any(
            row[k] != 0 for k in ("brought_forward", "charged", "paid", "credits", "balance")
        )
        overlaps = tenant.move_in_date <= end and (
            tenant.move_out_date is None or tenant.move_out_date >= start
        )
        if moving or (overlaps and tenant.is_billable):
            listed.append((tenant, row))
    return listed
