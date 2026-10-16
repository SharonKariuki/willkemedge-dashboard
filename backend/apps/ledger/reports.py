"""Accounting statements read straight from the general ledger.

Every figure on the Accounting page — and every file downloaded from it — comes
from ``JournalLine`` through the functions here, so the screen and the export
can never disagree.

Conventions
-----------
* **Dates.** An entry belongs to the period its ``date`` falls in. Periods are a
  ``start``–``end`` date range, both days inclusive.
* **Normal side.** Assets and expenses carry debit balances; liabilities,
  equity and income carry credit balances. A "balance" here is always on the
  account's normal side, so a positive figure is the usual state and a
  negative one is the unusual one (an overdrawn bank, a refund-heavy income).
* **Financial year** is the calendar year. Income and expense accounts start
  each year at zero — their opening balance on any date is the year-to-date
  movement — and everything they earned before 1 January sits in equity as
  profit brought forward. Balance-sheet accounts carry their whole history.
* **Building.** A filter by building keeps only entries tagged to it. Every
  journal entry balances on its own, so a building's books balance too.
"""
from __future__ import annotations

import datetime as _dt
from collections import defaultdict
from decimal import Decimal

from django.db.models import Q, Sum

from apps.expenses.models import Account, AccountType

from .models import JournalEntry, JournalLine

ZERO = Decimal("0.00")

DEBIT_NORMAL = {AccountType.ASSET, AccountType.EXPENSE}
PNL_TYPES = {AccountType.INCOME, AccountType.EXPENSE}

#: What posted the entry, as the ledger stores it → how it reads on a report.
SOURCE_LABELS = {
    "payment": "Payment",
    "expense": "Expense",
    "manual_income": "Manual income",
    "utility_charge": "Water / utility charge",
    "tenant_credit": "Tenant credit",
    "credit_application": "Credit applied",
    "tenant_refund": "Refund",
    "opening_ar": "Opening balance",
    "opening_deposit": "Opening deposit",
    "petty_topup": "Petty cash top-up",
    "deposit_refund": "Deposit refund",
    "arrear": "Rent billed",
}


def source_label(source_type: str) -> str:
    return SOURCE_LABELS.get(source_type or "", (source_type or "Manual").replace("_", " ").capitalize())


def _plain_text(text: str) -> str:
    return "".join(ch for ch in (text or "").lower() if ch.isalnum())


def line_detail(line, account_name: str) -> str:
    """A line's own note, when it says more than the entry's memo.

    Most lines carry only the account's name or a cut-down copy of the memo;
    a few say something the memo doesn't ("16% VAT on commercial rent").
    """
    detail = (line.description or "").strip()
    plain = _plain_text(detail)
    if not plain or plain == _plain_text(account_name):
        return ""
    if _plain_text(line.entry.memo).startswith(plain[:25]):
        return ""
    return detail


def _money(value) -> Decimal:
    return (Decimal(value) if value is not None else ZERO).quantize(Decimal("0.01"))


def year_start(day: _dt.date) -> _dt.date:
    return _dt.date(day.year, 1, 1)


def normal_balance(account_type: str, debit, credit) -> Decimal:
    """Debit minus credit, turned to the account's normal side."""
    debit, credit = _money(debit), _money(credit)
    return debit - credit if account_type in DEBIT_NORMAL else credit - debit


def _lines(building_id=None):
    qs = JournalLine.objects.filter(entry__is_posted=True)
    if building_id:
        qs = qs.filter(entry__building_id=building_id)
    return qs


def _sums(qs) -> dict[str, tuple[Decimal, Decimal]]:
    """``{account code: (debits, credits)}`` for a line queryset."""
    return {
        row["account__code"]: (_money(row["dr"]), _money(row["cr"]))
        for row in qs.values("account__code").annotate(dr=Sum("debit"), cr=Sum("credit"))
    }


def _accounts():
    return list(Account.objects.filter(is_active=True).order_by("code"))


def balances_as_of(day: _dt.date, *, building_id=None) -> dict[str, Decimal]:
    """Closing balance of every account at the end of ``day``.

    Balance-sheet accounts: everything up to ``day``. Income and expense
    accounts: the financial year to ``day`` only.
    """
    accounts = {a.code: a for a in _accounts() if not a.is_header}
    all_time = _sums(_lines(building_id).filter(entry__date__lte=day))
    this_year = _sums(_lines(building_id).filter(entry__date__gte=year_start(day), entry__date__lte=day))
    out = {}
    for code, acct in accounts.items():
        source = this_year if acct.account_type in PNL_TYPES else all_time
        dr, cr = source.get(code, (ZERO, ZERO))
        out[code] = normal_balance(acct.account_type, dr, cr)
    return out


def profit_brought_forward(day: _dt.date, *, building_id=None) -> Decimal:
    """Net profit of every year before ``day``'s — equity not yet closed off."""
    before = _sums(_lines(building_id).filter(entry__date__lt=year_start(day)))
    total = ZERO
    for acct in _accounts():
        if acct.is_header or acct.account_type not in PNL_TYPES:
            continue
        dr, cr = before.get(acct.code, (ZERO, ZERO))
        total += (cr - dr)  # income adds, expense subtracts
    return total


def opening_balances(start: _dt.date, *, building_id=None) -> dict[str, Decimal]:
    """Balance of each account at the start of ``start`` (close of the day before).

    Income and expense accounts open at zero on 1 January.
    """
    previous = start - _dt.timedelta(days=1)
    opening = balances_as_of(previous, building_id=building_id)
    if start == year_start(start):
        for acct in _accounts():
            if acct.account_type in PNL_TYPES and acct.code in opening:
                opening[acct.code] = ZERO
    return opening


# ── General ledger ───────────────────────────────────────────────────────────

def general_ledger(
    start: _dt.date,
    end: _dt.date,
    *,
    building_id=None,
    account_codes=None,
    sources=None,
    search: str = "",
) -> dict:
    """Every account's opening balance, dated lines and closing balance.

    The running balance on each line is the account's true balance after that
    line, counting every line in the period — ``sources`` and ``search`` only
    choose which lines are *shown*, so a filtered view still opens and closes
    on the real figures.
    """
    accounts = [a for a in _accounts() if not a.is_header]
    if account_codes:
        wanted = set(account_codes)
        accounts = [a for a in accounts if a.code in wanted]
    by_code = {a.code: a for a in accounts}
    opening = opening_balances(start, building_id=building_id)

    lines = (
        _lines(building_id)
        .filter(entry__date__gte=start, entry__date__lte=end, account__code__in=list(by_code))
        .select_related("entry", "entry__building", "account")
        .order_by("account__code", "entry__date", "entry__id", "id")
    )
    shown = Q()
    if sources:
        shown &= Q(entry__source_type__in=list(sources))
    if search:
        shown &= (
            Q(entry__memo__icontains=search)
            | Q(entry__reference__icontains=search)
            | Q(description__icontains=search)
        )
    shown_ids = set(lines.filter(shown).values_list("id", flat=True)) if (sources or search) else None

    grouped = defaultdict(list)
    for line in lines:
        grouped[line.account.code].append(line)

    result = []
    total_dr = total_cr = ZERO
    for acct in accounts:
        rows = grouped.get(acct.code, [])
        balance = opening.get(acct.code, ZERO)
        open_bal = balance
        out_rows = []
        dr_sum = cr_sum = ZERO
        year = start.year
        for line in rows:
            if acct.account_type in PNL_TYPES and line.entry.date.year != year:
                year = line.entry.date.year
                balance = ZERO  # income and expenses restart each 1 January
            dr, cr = _money(line.debit), _money(line.credit)
            balance += normal_balance(acct.account_type, dr, cr)
            if shown_ids is not None and line.id not in shown_ids:
                continue
            dr_sum += dr
            cr_sum += cr
            entry = line.entry
            out_rows.append({
                "date": entry.date,
                "entry_id": entry.id,
                "reference": entry.reference,
                "memo": entry.memo,
                "detail": line_detail(line, acct.name),
                "description": entry.memo,
                "source": source_label(entry.source_type),
                "source_type": entry.source_type,
                "kind": entry.kind,
                "building": entry.building.name if entry.building_id else "",
                "debit": dr,
                "credit": cr,
                "balance": balance,
            })
        if not out_rows and open_bal == ZERO and balance == ZERO and not account_codes:
            continue
        if shown_ids is not None and not out_rows and not account_codes:
            continue
        total_dr += dr_sum
        total_cr += cr_sum
        result.append({
            "code": acct.code,
            "name": acct.name,
            "type": acct.get_account_type_display(),
            "normal_side": "debit" if acct.account_type in DEBIT_NORMAL else "credit",
            "opening": open_bal,
            "debit": dr_sum,
            "credit": cr_sum,
            "closing": balance,
            "lines": out_rows,
        })
    return {
        "accounts": result,
        "total_debit": total_dr,
        "total_credit": total_cr,
        "line_count": sum(len(a["lines"]) for a in result),
        "filtered": shown_ids is not None,
    }


def journal(start, end, *, building_id=None, sources=None, search: str = "") -> dict:
    """Journal entries in date order, each with its balanced lines."""
    qs = JournalEntry.objects.filter(is_posted=True, date__gte=start, date__lte=end)
    if building_id:
        qs = qs.filter(building_id=building_id)
    if sources:
        qs = qs.filter(source_type__in=list(sources))
    if search:
        qs = qs.filter(
            Q(memo__icontains=search) | Q(reference__icontains=search)
            | Q(lines__description__icontains=search)
        ).distinct()
    qs = qs.select_related("building").prefetch_related("lines__account").order_by("date", "id")

    entries = []
    total = ZERO
    for entry in qs:
        lines = [
            {
                "account_code": line.account.code,
                "account_name": line.account.name,
                "description": line.description,
                "debit": _money(line.debit),
                "credit": _money(line.credit),
            }
            for line in sorted(entry.lines.all(), key=lambda ln: (-ln.debit, ln.account.code))
        ]
        amount = sum((ln["debit"] for ln in lines), ZERO)
        total += amount
        entries.append({
            "id": entry.id,
            "date": entry.date,
            "reference": entry.reference,
            "memo": entry.memo,
            "source": source_label(entry.source_type),
            "source_type": entry.source_type,
            "kind": entry.kind,
            "building": entry.building.name if entry.building_id else "",
            "amount": amount,
            "lines": lines,
        })
    return {"entries": entries, "total": total}


# ── Statements ───────────────────────────────────────────────────────────────

def _grouped(accounts, values: dict[str, Decimal], *, keep_zero=False) -> list[dict]:
    """Posting accounts under their section headers, zero lines dropped."""
    headers = {a.code: a for a in accounts if a.is_header}
    groups: dict[str, dict] = {}
    for acct in accounts:
        if acct.is_header:
            continue
        amount = values.get(acct.code, ZERO)
        if amount == ZERO and not keep_zero:
            continue
        header = headers.get(acct.parent_code)
        key = header.code if header else ""
        group = groups.setdefault(key, {
            "code": key, "name": header.name if header else "Other", "accounts": [], "total": ZERO,
        })
        group["accounts"].append({"code": acct.code, "name": acct.name, "amount": amount})
        group["total"] += amount
    return [groups[k] for k in sorted(groups)]


def profit_and_loss(start, end, *, building_id=None) -> dict:
    """Income less expenses for the period, every account that moved."""
    sums = _sums(_lines(building_id).filter(entry__date__gte=start, entry__date__lte=end))
    accounts = _accounts()
    values = {}
    for acct in accounts:
        if acct.is_header or acct.account_type not in PNL_TYPES:
            continue
        dr, cr = sums.get(acct.code, (ZERO, ZERO))
        values[acct.code] = normal_balance(acct.account_type, dr, cr)
    income = [a for a in accounts if a.account_type == AccountType.INCOME]
    expense = [a for a in accounts if a.account_type == AccountType.EXPENSE]
    income_groups = _grouped(income, values)
    expense_groups = _grouped(expense, values)
    total_income = sum((g["total"] for g in income_groups), ZERO)
    total_expenses = sum((g["total"] for g in expense_groups), ZERO)
    return {
        "income": income_groups,
        "expenses": expense_groups,
        "total_income": total_income,
        "total_expenses": total_expenses,
        "net_profit": total_income - total_expenses,
    }


def balance_sheet(as_of: _dt.date, *, building_id=None) -> dict:
    """Assets = liabilities + equity at the close of ``as_of``.

    Equity carries the year's profit to date and any earlier profit not yet
    closed off, so the two sides agree whenever the ledger itself balances.
    """
    balances = balances_as_of(as_of, building_id=building_id)
    accounts = _accounts()
    by_type = lambda t: [a for a in accounts if a.account_type == t]  # noqa: E731

    assets = _grouped(by_type(AccountType.ASSET), balances)
    liabilities = _grouped(by_type(AccountType.LIABILITY), balances)
    equity = _grouped(by_type(AccountType.EQUITY), balances)

    year_profit = sum(
        (balances.get(a.code, ZERO) for a in by_type(AccountType.INCOME) if not a.is_header), ZERO
    ) - sum(
        (balances.get(a.code, ZERO) for a in by_type(AccountType.EXPENSE) if not a.is_header), ZERO
    )
    brought_forward = profit_brought_forward(as_of, building_id=building_id)
    earnings = []
    if brought_forward:
        earnings.append({"code": "", "name": "Profit brought forward from earlier years", "amount": brought_forward})
    earnings.append({"code": "", "name": f"Profit for {as_of.year} to date", "amount": year_profit})
    equity.append({
        "code": "", "name": "Earnings", "accounts": earnings,
        "total": sum((e["amount"] for e in earnings), ZERO),
    })

    total_assets = sum((g["total"] for g in assets), ZERO)
    total_liabilities = sum((g["total"] for g in liabilities), ZERO)
    total_equity = sum((g["total"] for g in equity), ZERO)
    difference = total_assets - total_liabilities - total_equity
    return {
        "assets": assets,
        "liabilities": liabilities,
        "equity": equity,
        "total_assets": total_assets,
        "total_liabilities": total_liabilities,
        "total_equity": total_equity,
        "total_liabilities_and_equity": total_liabilities + total_equity,
        "difference": difference,
        "balanced": abs(difference) < Decimal("0.01"),
    }


def trial_balance(start, end, *, building_id=None, mode="balances") -> dict:
    """Debit and credit columns that must agree.

    ``balances``: every account's closing balance at ``end`` on its own side
    (income and expenses for the year to date, earlier years' profit as one
    equity line). ``movements``: total debits and credits posted between
    ``start`` and ``end``.
    """
    accounts = [a for a in _accounts() if not a.is_header]
    rows = []
    if mode == "movements":
        sums = _sums(_lines(building_id).filter(entry__date__gte=start, entry__date__lte=end))
        for acct in accounts:
            dr, cr = sums.get(acct.code, (ZERO, ZERO))
            if dr or cr:
                rows.append({"code": acct.code, "name": acct.name, "type": acct.get_account_type_display(),
                             "debit": dr, "credit": cr})
    else:
        balances = balances_as_of(end, building_id=building_id)
        for acct in accounts:
            amount = balances.get(acct.code, ZERO)
            if not amount:
                continue
            on_debit = (acct.account_type in DEBIT_NORMAL) == (amount > 0)
            rows.append({
                "code": acct.code, "name": acct.name, "type": acct.get_account_type_display(),
                "debit": abs(amount) if on_debit else ZERO,
                "credit": ZERO if on_debit else abs(amount),
            })
        brought_forward = profit_brought_forward(end, building_id=building_id)
        if brought_forward:
            rows.append({
                "code": "", "name": "Profit brought forward from earlier years", "type": "Equity",
                "debit": -brought_forward if brought_forward < 0 else ZERO,
                "credit": brought_forward if brought_forward > 0 else ZERO,
            })
    total_dr = sum((r["debit"] for r in rows), ZERO)
    total_cr = sum((r["credit"] for r in rows), ZERO)
    return {
        "mode": mode,
        "rows": rows,
        "total_debit": total_dr,
        "total_credit": total_cr,
        "balanced": abs(total_dr - total_cr) < Decimal("0.01"),
    }


def chart_of_accounts(start, end, *, building_id=None) -> dict:
    """The whole chart: each account's opening, movements and closing balance."""
    accounts = _accounts()
    opening = opening_balances(start, building_id=building_id)
    closing = balances_as_of(end, building_id=building_id)
    sums = _sums(_lines(building_id).filter(entry__date__gte=start, entry__date__lte=end))
    rows = []
    for acct in accounts:
        if acct.is_header:
            rows.append({"code": acct.code, "name": acct.name, "type": acct.get_account_type_display(),
                         "is_header": True, "parent_code": acct.parent_code})
            continue
        dr, cr = sums.get(acct.code, (ZERO, ZERO))
        rows.append({
            "code": acct.code, "name": acct.name, "type": acct.get_account_type_display(),
            "is_header": False, "parent_code": acct.parent_code,
            "opening": opening.get(acct.code, ZERO), "debit": dr, "credit": cr,
            "closing": closing.get(acct.code, ZERO),
        })
    # Section subtotals of the closing balances.
    for row in rows:
        if row["is_header"]:
            row["closing"] = sum(
                (r["closing"] for r in rows if not r["is_header"] and r["parent_code"] == row["code"]), ZERO
            )
    return {"accounts": rows}


def budget_vs_actual(start, end, *, building_id=None) -> dict:
    """Budgets set for the months in the period against what the ledger shows."""
    from apps.ledger.models import Budget
    from apps.tenants.models import Tenant, TenantStatus

    months = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        months.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    in_range = Q()
    for y, m in months:
        in_range |= Q(period_year=y, period_month=m)

    sums = _sums(_lines(building_id).filter(entry__date__gte=start, entry__date__lte=end))
    budgets = Budget.objects.filter(in_range).select_related("account")
    if building_id:
        budgets = budgets.filter(building_id=building_id)

    rows = []
    if budgets.exists():
        per_account = defaultdict(lambda: ZERO)
        meta = {}
        for b in budgets:
            per_account[b.account.code] += _money(b.amount)
            meta[b.account.code] = b.account
        for code in sorted(per_account):
            acct = meta[code]
            dr, cr = sums.get(code, (ZERO, ZERO))
            actual = normal_balance(acct.account_type, dr, cr)
            rows.append({"category": f"{code} — {acct.name}", "budgeted": per_account[code],
                         "actual": actual, "variance": actual - per_account[code]})
        basis = "budgets"
    else:
        # No budget set: rent received against the rent the current tenants owe.
        actual = sum(
            (normal_balance(AccountType.INCOME, *sums.get(code, (ZERO, ZERO))) for code in ("4110", "4120")),
            ZERO,
        )
        tenants = Tenant.objects.filter(status=TenantStatus.ACTIVE, is_billable=True)
        if building_id:
            tenants = tenants.filter(unit__building_id=building_id)
        expected = _money(tenants.aggregate(t=Sum("monthly_rent"))["t"]) * len(months)
        rows.append({"category": "Rent (current tenants)", "budgeted": expected,
                     "actual": actual, "variance": actual - expected})
        basis = "rent_roll"
    total_b = sum((r["budgeted"] for r in rows), ZERO)
    total_a = sum((r["actual"] for r in rows), ZERO)
    return {"basis": basis, "rows": rows, "total_budgeted": total_b,
            "total_actual": total_a, "total_variance": total_a - total_b}
