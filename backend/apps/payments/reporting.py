"""
What tenant credits and refunds do to the income and expense reports.

The Accounting page and the trial balance read the general ledger, so credits
reach them the moment they post. The Reports page does not: its P&L, annual
income summary and expense breakdown are built from ``Payment`` and ``Expense``
rows, which know nothing about a credit. Without the adjustments here, a rent
concession would leave income untouched on one page and reduced on the other.

Every rule below is the report-side reading of the entry the credit posts
(see ``apps.ledger.posting``, tenant credits section):

  credit note (rent or water)   DR 4110/4120/4150 + 2600   income DOWN by the net
  credit applied to rent        DR 1040 / CR income + VAT  income UP   by the net
  tenant paid a cost that was
  ours                          DR <expense account>       expense UP by the amount
  credit owed from before       DR 3300 Retained Earnings  neither — it is equity
  refund of a credit            DR 1040 / CR 1020          neither — balance sheet
  refund of overpaid rent       DR 4110/4120 + 2600        income DOWN by the net

VAT never counts as income on either side: it is a liability owed to KRA (2600),
and the payment-derived reports already strip it out of commercial receipts.

A credit note that is applied to the very charge it corrects nets to nothing
here, exactly as it does in the ledger: income that was never recognised cannot
be reduced.
"""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Count, Sum

from apps.buildings.models import UnitClassification

from .models import (
    CreditApplication,
    CreditReason,
    CreditStatus,
    Refund,
    RefundLine,
    RefundStatus,
    TenantCredit,
)
from .tax_service import split_tax_inclusive

ZERO = Decimal("0.00")

#: Reasons whose debit is an income account, so the credit reduces income.
INCOME_REASONS = (CreditReason.BILLING_CORRECTION, CreditReason.RENT_CONCESSION)


def _in_building(queryset, building_id, path: str):
    return queryset.filter(**{f"{path}__unit__building_id": building_id}) if building_id else queryset


def _period(queryset, field: str, month: int | None, year: int | None):
    if year is not None:
        queryset = queryset.filter(**{f"{field}__year": year})
    if month is not None:
        queryset = queryset.filter(**{f"{field}__month": month})
    return queryset


def credit_notes_net(month=None, year=None, *, building_id=None) -> Decimal:
    """Income given back by credit notes in the period, before VAT."""
    qs = TenantCredit.objects.filter(status=CreditStatus.ISSUED, reason__in=INCOME_REASONS)
    qs = _period(_in_building(qs, building_id, "tenant"), "credit_date", month, year)
    return qs.aggregate(t=Sum("net_amount"))["t"] or ZERO


def credit_applied_net(month=None, year=None, *, building_id=None) -> Decimal:
    """Rent recognised in the period because a credit settled it, before VAT.

    Rent is on a cash basis, so a month settled by credit is earned when the
    credit is applied — the same moment the ledger recognises it.
    """
    qs = CreditApplication.objects.filter(
        reversed_at__isnull=True, credit__status=CreditStatus.ISSUED,
    ).select_related("arrears")
    qs = _period(_in_building(qs, building_id, "credit__tenant"), "applied_on", month, year)
    total = ZERO
    for application in qs:
        arrear = application.arrears
        obligation = (arrear.expected_rent or ZERO) + (arrear.expected_vat or ZERO)
        vat = ZERO
        if arrear.expected_vat and obligation > 0:
            vat = (application.amount * arrear.expected_vat / obligation).quantize(Decimal("0.01"))
        total += application.amount - vat
    return total


def refunded_income_net(month=None, year=None, *, building_id=None) -> Decimal:
    """Income reversed by refunding overpaid rent, before VAT.

    Only the part drawn from overpaid rent: that cash was booked straight to
    income when it arrived. A refund drawn from a credit moves 1040 and the bank
    and touches no income account.
    """
    qs = RefundLine.objects.filter(
        credit__isnull=True, refund__status=RefundStatus.SENT,
    ).select_related("refund")
    qs = _period(_in_building(qs, building_id, "refund__tenant"), "refund__sent_on", month, year)
    total = ZERO
    for line in qs:
        if line.refund.unit_classification == UnitClassification.BUSINESS:
            total += split_tax_inclusive(line.amount, UnitClassification.BUSINESS).base_amount
        else:
            total += line.amount
    return total


def income_adjustment(month=None, year=None, *, building_id=None) -> Decimal:
    """What credits add to (or take off) the period's income, net of VAT.

    Add this to any income figure derived from ``Payment`` rows.
    """
    return (
        credit_applied_net(month, year, building_id=building_id)
        - credit_notes_net(month, year, building_id=building_id)
        - refunded_income_net(month, year, building_id=building_id)
    )


def expense_addition_rows(month=None, year=None, *, building_id=None) -> list[dict]:
    """Costs the tenant bore for us, as expense rows: category, total, count.

    The landlord's cost is real and already in the ledger against the category's
    own account; it simply never had an ``Expense`` row, so the expense reports
    have to be told about it.
    """
    qs = TenantCredit.objects.filter(
        status=CreditStatus.ISSUED,
        reason=CreditReason.TENANT_PAID_COST,
        expense_category__isnull=False,
    )
    qs = _period(_in_building(qs, building_id, "tenant"), "credit_date", month, year)
    return [
        {
            "category": row["expense_category__name"],
            "total": row["total"] or ZERO,
            "count": row["n"],
        }
        for row in qs.values("expense_category__name").annotate(total=Sum("amount"), n=Count("id"))
    ]


def expense_additions(month=None, year=None, *, building_id=None) -> dict[str, Decimal]:
    """``{expense category name: amount}`` for costs the tenant bore for us."""
    return {
        row["category"]: row["total"]
        for row in expense_addition_rows(month, year, building_id=building_id)
    }


def expense_addition_total(month=None, year=None, *, building_id=None) -> Decimal:
    return sum(expense_additions(month, year, building_id=building_id).values(), ZERO)


def has_credit_activity(month=None, year=None, *, building_id=None) -> bool:
    """Whether any credit or refund touched the period — lets a report say so."""
    credits_qs = _period(
        _in_building(TenantCredit.objects.filter(status=CreditStatus.ISSUED), building_id, "tenant"),
        "credit_date", month, year,
    )
    refunds_qs = _period(
        _in_building(Refund.objects.filter(status=RefundStatus.SENT), building_id, "tenant"),
        "sent_on", month, year,
    )
    applications_qs = _period(
        _in_building(
            CreditApplication.objects.filter(reversed_at__isnull=True), building_id, "credit__tenant"
        ),
        "applied_on", month, year,
    )
    return credits_qs.exists() or refunds_qs.exists() or applications_qs.exists()


__all__ = [
    "credit_applied_net",
    "credit_notes_net",
    "expense_addition_rows",
    "expense_addition_total",
    "expense_additions",
    "has_credit_activity",
    "income_adjustment",
    "refunded_income_net",
]
