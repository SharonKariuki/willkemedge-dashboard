"""Where each tenant's books begin.

A tenant with an ``OpeningBalance`` has their account restarted at its
``as_of`` date (31 August 2026 for the September restart): the landlord's
balance on that day is carried in as one figure, and every row from before it
is history — kept on file, never deleted, but counted nowhere. A tenant without
one keeps their whole history, exactly as before, so a building moves onto its
sheet figure only when its opening balances are loaded.

Every balance the product reports reads its rows through these filters: the
rent roll and ``current_balances``, the statement, aging, payment allocation,
the dashboard and reports. They have to agree, or a tenant's balance would
depend on which page you looked at.

What is inside the books, for a tenant whose books open on ``books_from``:

  rent (Arrears)            period on or after the books month
  metered water             invoiced with a rent period in the books — usage
                            for the opening month itself rides on the first
                            invoice (August's water is billed with September's
                            rent), exactly as ``meter_service.invoiced_with``
  other charges             posted on or after ``books_from``
  payments, credits         dated on or after ``books_from``
  refunds                   sent on or after ``books_from``

Deposits are not cut: what 2100 holds is cumulative, whenever it arrived.
"""
from __future__ import annotations

import datetime as _dt
from decimal import Decimal

from django.db.models import F, Q
from django.db.models.lookups import GreaterThanOrEqual

ZERO = Decimal("0.00")

_OB = "opening_balance"


def _no_opening(prefix: str) -> Q:
    return Q(**{f"{prefix}tenant__{_OB}__isnull": True})


def _period_on_or_after(prefix: str, offset: int = 0) -> Q:
    """``period`` (year*12+month) at or after the tenant's books month, less ``offset``."""
    lhs = F(f"{prefix}period_year") * 12 + F(f"{prefix}period_month")
    rhs = F(f"{prefix}tenant__{_OB}__books_key")
    if offset:
        rhs = rhs - offset
    return Q(GreaterThanOrEqual(lhs, rhs))


def _dated_on_or_after(field: str, prefix: str) -> Q:
    return Q(**{f"{prefix}{field}__gt": F(f"{prefix}tenant__{_OB}__as_of")})


def arrears_q(prefix: str = "") -> Q:
    """Rent rows (``Arrears``) inside the tenant's books."""
    return _no_opening(prefix) | _period_on_or_after(prefix)


def metered_q(prefix: str = "") -> Q:
    """Charges that are metered usage — mirrors ``meter_service.is_metered_usage``."""
    from .meter_service import WATER_LABEL

    return Q(**{f"{prefix}closing_reading__isnull": False}) | Q(**{f"{prefix}label": WATER_LABEL})


def utilities_q(prefix: str = "") -> Q:
    """Water and other charges (``UtilityCharge``) inside the tenant's books."""
    metered = metered_q(prefix)
    return (
        _no_opening(prefix)
        | (metered & _period_on_or_after(prefix, offset=1))
        | (~metered & _dated_on_or_after("posting_date", prefix))
    )


def payments_q(prefix: str = "") -> Q:
    return _no_opening(prefix) | _dated_on_or_after("payment_date", prefix)


def credits_q(prefix: str = "") -> Q:
    return _no_opening(prefix) | _dated_on_or_after("credit_date", prefix)


def refunds_q(prefix: str = "") -> Q:
    return _no_opening(prefix) | _dated_on_or_after("sent_on", prefix)


# ── one tenant, in Python ────────────────────────────────────────────────────

def opening_for(tenant):
    """The tenant's ``OpeningBalance``, or ``None`` when their full history counts."""
    from .models import OpeningBalance

    tenant_id = tenant.pk if hasattr(tenant, "pk") else int(tenant)
    return OpeningBalance.objects.filter(tenant_id=tenant_id).first()


def opening_amounts(tenant_ids, *, before: _dt.date | None = None) -> dict[int, Decimal]:
    """``{tenant_id: amount}`` for the tenants that have an opening balance.

    ``before`` leaves out an opening dated on or after it: a balance asked for
    as at a month before the books began has nothing carried into it yet.
    """
    from .models import OpeningBalance

    rows = OpeningBalance.objects.filter(tenant_id__in=list(tenant_ids))
    if before is not None:
        rows = rows.filter(as_of__lt=before)
    return {tid: Decimal(amount) for tid, amount in rows.values_list("tenant_id", "amount")}


def period_in_books(opening, year: int, month: int) -> bool:
    return opening is None or year * 12 + month >= opening.books_key


def date_in_books(opening, day: _dt.date | None) -> bool:
    return opening is None or (day is not None and day > opening.as_of)


def utility_in_books(opening, charge) -> bool:
    from .meter_service import is_metered_usage

    if opening is None:
        return True
    if is_metered_usage(charge):
        return charge.period_year * 12 + charge.period_month >= opening.books_key - 1
    return charge.posting_date > opening.as_of


# ── the rent subledger of a restarted account ────────────────────────────────
#
# ``Arrears.balance`` records which months are still open; the rent roll
# records what is owed. Payments are tagged to the month FIFO settled, and
# before the restart that was often a month now outside the books — September
# cash that cleared July leaves September looking unpaid. The restart sets the
# open months straight from the balance instead: whatever the tenant owes sits
# on their newest months (oldest debt is paid first), the rest are settled.


def _row_credit_floor(row) -> Decimal:
    """Credit on ``row`` that numbered credits (Add Credit) put there."""
    from django.db.models import Sum

    from .models import CreditApplication

    return Decimal(
        CreditApplication.objects.filter(arrears=row, reversed_at__isnull=True)
        .aggregate(t=Sum("amount"))["t"] or ZERO
    )


def unapplied_credit(tenant) -> Decimal:
    """Credit a restarted tenant has in hand that no open month has used yet.

    The account's balance counts every month raised, open or not; the months
    still open are owed but uncovered. Whatever credit the balance shows beyond
    them is free to pay the next month raised. Numbered credits are left out:
    they are applied by their own path (``credits.apply_account_credits``).
    """
    from django.db.models import Sum

    from .credits import account_balance, manual_credit_available
    from .models import Arrears

    still_open = Decimal(
        Arrears.objects.filter(arrears_q(), tenant=tenant, balance__gt=0)
        .aggregate(t=Sum("balance"))["t"] or ZERO
    )
    free = still_open - account_balance(tenant) - manual_credit_available(tenant)
    return max(free, ZERO).quantize(Decimal("0.01"))


def resettle(tenant) -> list[tuple]:
    """Set a restarted tenant's open months from their balance.

    Returns ``[(row, balance_before, balance_after), …]`` for the rows changed.
    """
    from django.db import transaction

    from .credits import account_balance
    from .models import Arrears

    changed = []
    with transaction.atomic():
        rows = list(
            Arrears.objects.select_for_update(of=("self",))
            .filter(arrears_q(), tenant=tenant)
            .order_by("-period_year", "-period_month")
        )
        owed = max(account_balance(tenant), ZERO)
        for row in rows:
            obligation = Decimal(row.expected_total) - Decimal(row.waived_amount or ZERO)
            still_owed = min(max(obligation, ZERO), owed)
            owed -= still_owed
            settled = obligation - still_owed
            credit = max(
                settled - Decimal(row.amount_paid or ZERO),
                _row_credit_floor(row),
                ZERO,
            )
            before = (row.credit_applied, row.balance, row.is_cleared)
            row.credit_applied = credit
            row.balance = max(Decimal(row.expected_total) - Decimal(row.covered), ZERO)
            row.is_cleared = row.covered >= row.expected_total
            if (row.credit_applied, row.balance, row.is_cleared) != before:
                row.save(update_fields=["credit_applied", "balance", "is_cleared", "updated_at"])
                changed.append((row, before[1], row.balance))
    return changed


def hidden_balance(tenant, opening=None) -> Decimal:
    """What the rows outside a restarted tenant's books still add to 1040.

    The general ledger keeps every entry those rows posted — history is not
    rewritten — so the opening journal has to bring 1040 from this figure to
    the sheet's. Mirrors the posting rules: rent and its VAT less waivers,
    water and other charges, less receipts (deposits never touch 1040; a void
    is reversed), less credits still issued, plus refunds sent.
    """
    from django.db.models import Sum

    from .credits import issued_credits, sent_refunds
    from .models import Arrears, Payment, PaymentType, UtilityCharge

    opening = opening or opening_for(tenant)
    if opening is None:
        return ZERO

    def _sum(qs, field="amount"):
        return Decimal(qs.aggregate(t=Sum(field))["t"] or ZERO)

    before_books = {"period_year__lt": opening.books_year}
    rent = Arrears.objects.filter(tenant=tenant).filter(
        Q(**before_books) | Q(period_year=opening.books_year, period_month__lt=opening.books_month)
    )
    total = _sum(rent, "expected_rent") + _sum(rent, "expected_vat") - _sum(rent, "waived_amount")
    total += sum(
        (Decimal(u.amount) for u in UtilityCharge.objects.filter(tenant=tenant)
         if not utility_in_books(opening, u)),
        ZERO,
    )
    total -= _sum(
        Payment.objects.filter(tenant=tenant, voided_at__isnull=True, payment_date__lte=opening.as_of)
        .exclude(payment_type=PaymentType.DEPOSIT)
    )
    total -= _sum(issued_credits([tenant.pk]).filter(credit_date__lte=opening.as_of))
    total += _sum(sent_refunds([tenant.pk]).filter(sent_on__lte=opening.as_of))
    return total.quantize(Decimal("0.01"))
