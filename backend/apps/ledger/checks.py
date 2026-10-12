"""
Ledger integrity checks — the tests an auditor runs before trusting the books.

Each check compares the general ledger with the records it is built from:

  balanced         every journal entry's debits equal its credits
  complete         every payment, rent charge, water charge, expense and manual
                   income has its entry, and every voided payment its reversal
  no orphans       no entry still counts money whose source row is gone
  receivable       1040 equals the rent roll — the sum of every tenant's
                   balance (``monthly_ledger.current_balances``), i.e. the
                   debtors list ties to the balance sheet
  deposits         1030 (deposit bank) equals 2100 (deposits held)

Used by ``manage.py check_ledger`` and ``manage.py rebuild_ledger``.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from decimal import Decimal

from django.db.models import Q, Sum

ZERO = Decimal("0.00")


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str


def account_balance(code: str, *, before: _dt.date | None = None) -> Decimal:
    """Debit-minus-credit balance of one account, optionally before a date."""
    from .models import JournalLine

    qs = JournalLine.objects.filter(account__code=code, entry__is_posted=True)
    if before is not None:
        qs = qs.filter(entry__date__lt=before)
    agg = qs.aggregate(d=Sum("debit"), c=Sum("credit"))
    return (agg["d"] or ZERO) - (agg["c"] or ZERO)


def _first_of_next_month(day: _dt.date) -> _dt.date:
    return (day.replace(day=1) + _dt.timedelta(days=32)).replace(day=1)


def rent_roll_total(today: _dt.date) -> Decimal:
    """What every tenant owes (less what is held in credit) at ``today``."""
    from apps.payments.monthly_ledger import current_balances
    from apps.tenants.models import Tenant

    ids = list(Tenant.objects.values_list("pk", flat=True))
    return sum(current_balances(ids, today=today).values(), ZERO)


def _check_balanced() -> CheckResult:
    from .models import JournalEntry

    bad = [
        e.pk
        for e in JournalEntry.objects.annotate(d=Sum("lines__debit"), c=Sum("lines__credit"))
        if (e.d or ZERO) != (e.c or ZERO)
    ]
    return CheckResult(
        "Every entry balances", not bad,
        f"{len(bad)} unbalanced: {bad[:10]}" if bad else "all entries balance",
    )


def _sources():
    """``{source_type: set(ids that must carry a NORMAL entry)}``."""
    from apps.expenses.models import Expense, ManualIncome
    from apps.payments.models import Arrears, Payment, UtilityCharge

    from .posting import _arrear_lines

    money = Q(expected_rent__gt=0) | Q(expected_vat__gt=0) | Q(waived_amount__gt=0)
    charged = {
        a.pk
        for a in Arrears.objects.filter(money).select_related("tenant__unit")
        # An opening row whose waiver cancels it carries nothing to post.
        if any(d or c for _code, d, c, _desc in _arrear_lines(a)[0])
    }
    return {
        "payment": set(Payment.objects.values_list("pk", flat=True)),
        "expense": set(
            Expense.objects.filter(category__account__isnull=False).values_list("pk", flat=True)
        ),
        "manual_income": set(ManualIncome.objects.values_list("pk", flat=True)),
        "utility_charge": set(
            UtilityCharge.objects.exclude(amount=0).values_list("pk", flat=True)
        ),
        "arrear": charged,
    }


def _live_ids() -> dict[str, set]:
    """``{source_type: set(ids of every row that still exists)}``."""
    from apps.expenses.models import Expense, ManualIncome
    from apps.payments.models import Arrears, Payment, UtilityCharge

    return {
        st: set(model.objects.values_list("pk", flat=True))
        for st, model in (
            ("payment", Payment), ("expense", Expense), ("manual_income", ManualIncome),
            ("utility_charge", UtilityCharge), ("arrear", Arrears),
        )
    }


def _entries(kind: str) -> dict[str, set]:
    from .models import JournalEntry

    out: dict[str, set] = {}
    for st, sid in JournalEntry.objects.filter(kind=kind).values_list("source_type", "source_id"):
        out.setdefault(st, set()).add(sid)
    return out


def _check_complete() -> CheckResult:
    from apps.payments.models import Payment

    normal = _entries("normal")
    reversal = _entries("reversal")
    missing = {
        st: sorted(ids - normal.get(st, set()))
        for st, ids in _sources().items()
        if ids - normal.get(st, set())
    }
    voided = set(Payment.objects.filter(voided_at__isnull=False).values_list("pk", flat=True))
    unreversed = sorted(voided - reversal.get("payment", set()))
    if unreversed:
        missing["voided payment without reversal"] = unreversed
    detail = "; ".join(f"{k}: {v[:10]}" for k, v in missing.items())
    return CheckResult("Every record is posted", not missing, detail or "nothing missing")


def orphan_entries():
    """Entries still counting money whose source row no longer exists.

    Returns ``(normals_without_reversal, reversals_without_normal)``, each a
    list of JournalEntry.
    """
    from .models import JournalEntry

    normal = _entries("normal")
    reversal = _entries("reversal")
    lone_normals, lone_reversals = [], []
    for st, live in _live_ids().items():
        gone_normals = normal.get(st, set()) - live - reversal.get(st, set())
        gone_reversals = reversal.get(st, set()) - live - normal.get(st, set())
        lone_normals += list(JournalEntry.objects.filter(
            source_type=st, source_id__in=gone_normals, kind="normal"))
        lone_reversals += list(JournalEntry.objects.filter(
            source_type=st, source_id__in=gone_reversals, kind="reversal"))
    return lone_normals, lone_reversals


def _check_orphans() -> CheckResult:
    lone_normals, lone_reversals = orphan_entries()
    bits = []
    if lone_normals:
        bits.append("source deleted but never reversed: " + ", ".join(
            f"{e.source_type}#{e.source_id}" for e in lone_normals[:10]))
    if lone_reversals:
        bits.append("reversal of an entry that no longer exists: " + ", ".join(
            f"{e.source_type}#{e.source_id}" for e in lone_reversals[:10]))
    return CheckResult("No orphan entries", not bits, "; ".join(bits) or "none")


def _check_receivable(today: _dt.date) -> CheckResult:
    gl = account_balance("1040", before=_first_of_next_month(today))
    roll = rent_roll_total(today)
    diff = gl - roll
    return CheckResult(
        "1040 ties to the rent roll", diff == ZERO,
        f"GL 1040 {gl:,.2f} vs rent roll {roll:,.2f} (difference {diff:,.2f})",
    )


def _check_deposits() -> CheckResult:
    bank = account_balance("1030")
    held = -account_balance("2100")
    diff = bank - held
    return CheckResult(
        "Deposit bank equals deposits held", diff == ZERO,
        f"1030 {bank:,.2f} vs 2100 {held:,.2f} (difference {diff:,.2f})",
    )


def run_checks(today: _dt.date | None = None) -> list[CheckResult]:
    from django.utils import timezone

    today = today or timezone.localdate()
    return [
        _check_balanced(),
        _check_complete(),
        _check_orphans(),
        _check_receivable(today),
        _check_deposits(),
    ]
