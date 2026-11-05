"""
Settling a tenant's security deposit when they leave.

The owner states what is kept back, line by line — the unpaid balance, damages,
cleaning, anything else — and what goes back to the tenant, either as whatever
is left, a fixed amount or a percentage of the deposit. Every shilling of the
deposit has to be accounted for: if the refund and the deductions do not add up
to the deposit held, nothing is saved.

What each part does to the tenant's account and the books:

    unpaid balance     a numbered TenantCredit (reason ``deposit_applied``) on
                       the settlement date, applied to the rent still open — so
                       the rent roll, arrears and statement settle exactly as
                       they do for any other credit
    damages, cleaning  kept against the cost they recover (the expense
    and other          category), never on the tenant's account
    refund             set aside until it is sent; posts DR 2100 / CR 1030 then

The postings are in ``apps.ledger.posting`` (deposit settlement section). Like
the credits service, every function here is atomic, locks the tenant first,
posts strictly — if the ledger refuses an entry the whole action rolls back —
and writes an AuditLog row. Owner-only: the owner settles and approves, and
the record says so (``approval_mode="owner_self"``).
"""
from __future__ import annotations

import datetime as _dt
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.utils import timezone

from apps.accounts import audit
from apps.expenses.models import ExpenseCategory
from apps.tenants.deposits import deposit_held_on_books
from apps.tenants.models import TenantStatus

from . import credits
from .credits import CreditError
from .models import (
    CreditReason,
    DeductionKind,
    DepositDeduction,
    DepositRefundStatus,
    DepositSettlement,
    PaymentSource,
    RefundBasis,
)

ZERO = Decimal("0.00")
CENTS = Decimal("0.01")
HUNDRED = Decimal("100")
SERIES = "DS"

#: Only a tenant on their way out — or already gone — has a deposit to settle.
SETTLEABLE_STATUSES = (TenantStatus.NOTICE_GIVEN, TenantStatus.MOVED_OUT)

#: The expense account each kind of deduction recovers, unless the owner picks
#: another category. Codes are from the auditor-locked chart.
DEFAULT_ACCOUNT_FOR_KIND = {
    DeductionKind.DAMAGES: "5200",   # Repairs & Maintenance
    DeductionKind.CLEANING: "5220",  # Cleaning & Garbage Collection
}


def _money(value) -> Decimal:
    return credits._money(value)


def default_category(kind: str) -> ExpenseCategory | None:
    code = DEFAULT_ACCOUNT_FOR_KIND.get(kind)
    if code is None:
        return None
    return (
        ExpenseCategory.objects.filter(account__code=code).order_by("name").first()
    )


def live_settlement(tenant) -> DepositSettlement | None:
    return DepositSettlement.objects.filter(tenant=tenant, voided_at__isnull=True).first()


def balance_owed(tenant) -> Decimal:
    """What the tenant owes on their account — rent, water, anything invoiced."""
    return max(credits.account_balance(tenant), ZERO)


def preview(tenant) -> dict:
    """Everything the Settle Deposit form needs to start from."""
    return {
        "deposit_held": deposit_held_on_books(tenant),
        "balance_owed": balance_owed(tenant),
        "can_settle": tenant.status in SETTLEABLE_STATUSES,
        "settlement": live_settlement(tenant),
        "default_categories": {
            kind: (cat.pk if (cat := default_category(kind)) else None)
            for kind in DEFAULT_ACCOUNT_FOR_KIND
        },
    }


def refund_for(basis: str, *, held: Decimal, deductions: Decimal, amount=None, percentage=None) -> Decimal:
    """The refund the owner asked for, in shillings."""
    if basis == RefundBasis.REMAINDER:
        return held - deductions
    if basis == RefundBasis.AMOUNT:
        if amount is None:
            raise CreditError("Enter the amount to refund.")
        return _money(amount)
    if basis == RefundBasis.PERCENTAGE:
        if percentage is None:
            raise CreditError("Enter the percentage of the deposit to refund.")
        pct = Decimal(str(percentage))
        if not ZERO <= pct <= HUNDRED:
            raise CreditError("The percentage must be between 0 and 100.")
        return (held * pct / HUNDRED).quantize(CENTS, rounding=ROUND_HALF_UP)
    raise CreditError("Choose how the refund is stated.")


def _clean_deductions(lines, *, owed: Decimal) -> list[dict]:
    clean = []
    for line in lines or []:
        try:
            kind = DeductionKind(line.get("kind"))
        except ValueError:
            raise CreditError("Choose what each deduction is for.") from None
        amount = _money(line.get("amount") or 0)
        if amount <= 0:
            raise CreditError(f"Enter an amount for the {kind.label.lower()} deduction.")
        description = (line.get("description") or "").strip() or kind.label
        category = line.get("expense_category")
        if kind == DeductionKind.UNPAID_BALANCE:
            category = None
        else:
            category = category or default_category(kind)
            if category is None or not category.account_id:
                raise CreditError(
                    f"Choose the cost the {kind.label.lower()} deduction recovers."
                )
        clean.append({
            "kind": kind, "amount": amount, "description": description[:200],
            "expense_category": category,
        })

    unpaid = [d for d in clean if d["kind"] == DeductionKind.UNPAID_BALANCE]
    if len(unpaid) > 1:
        raise CreditError("Enter the unpaid balance as one line.")
    if unpaid and unpaid[0]["amount"] > owed:
        raise CreditError(
            f"The tenant owes KES {owed:,.2f}; the deposit cannot settle more than that."
            if owed > 0 else "The tenant owes nothing, so there is no unpaid balance to deduct."
        )
    return clean


@transaction.atomic
def settle_deposit(
    *,
    tenant,
    settlement_date: _dt.date,
    deductions: list[dict],
    refund_basis: str,
    refund_amount=None,
    refund_percentage=None,
    method: str = "",
    paid_to: str = "",
    reference: str = "",
    sent_on: _dt.date | None = None,
    notes: str = "",
    actor=None,
    today: _dt.date | None = None,
) -> DepositSettlement:
    """Settle the deposit: keep the deductions, refund the rest, post it all."""
    from apps.ledger.posting import post_deposit_settlement, post_deposit_settlement_refund

    today = credits._today(today)
    credits._lock_tenant(tenant)
    tenant.refresh_from_db()

    if tenant.status not in SETTLEABLE_STATUSES:
        raise CreditError("Record the tenant's move-out notice or move-out before settling the deposit.")
    if live_settlement(tenant) is not None:
        raise CreditError("This deposit has already been settled. Void that settlement to redo it.")
    if settlement_date > today:
        raise CreditError("A settlement cannot be dated in the future.")
    if settlement_date < tenant.move_in_date:
        raise CreditError("A settlement cannot be dated before the tenant moved in.")

    held = deposit_held_on_books(tenant)
    if held <= 0:
        raise CreditError("There is no deposit on the books to settle.")
    owed = balance_owed(tenant)
    lines = _clean_deductions(deductions, owed=owed)
    total = sum((d["amount"] for d in lines), ZERO)
    if total > held:
        raise CreditError(
            f"The deductions come to KES {total:,.2f}, more than the KES {held:,.2f} deposit. "
            "Anything beyond the deposit stays on the tenant's account."
        )

    try:
        basis = RefundBasis(refund_basis)
    except ValueError:
        raise CreditError("Choose how the refund is stated.") from None
    refund = refund_for(basis, held=held, deductions=total, amount=refund_amount, percentage=refund_percentage)
    if refund < 0 or refund > held:
        raise CreditError(f"The refund must be between KES 0 and the KES {held:,.2f} deposit.")
    gap = held - total - refund
    if gap != 0:
        if gap > 0:
            raise CreditError(
                f"KES {gap:,.2f} of the deposit is not accounted for. Itemise it as a "
                "deduction, or refund it."
            )
        raise CreditError(
            f"The refund and the deductions come to KES {-gap:,.2f} more than the deposit."
        )

    if method:
        try:
            method = PaymentSource(method)
        except ValueError:
            raise CreditError("Choose how the refund is being sent.") from None
    refund_status = DepositRefundStatus.NONE
    if refund > 0:
        if sent_on is not None:
            if not method:
                raise CreditError("Choose how the refund was sent.")
            credits._validate_sent(method, reference, sent_on, today)
            if sent_on < settlement_date:
                raise CreditError("The refund cannot have been sent before the deposit was settled.")
            refund_status = DepositRefundStatus.SENT
        else:
            refund_status = DepositRefundStatus.TO_SEND

    user = credits._actor(actor)
    now = timezone.now()
    sent = refund_status == DepositRefundStatus.SENT
    settlement = DepositSettlement.objects.create(
        number=credits._next_number(SERIES),
        tenant=tenant,
        settlement_date=settlement_date,
        deposit_held=held,
        balance_owed=owed,
        deductions_total=total,
        refund_basis=basis,
        refund_percentage=Decimal(str(refund_percentage)) if basis == RefundBasis.PERCENTAGE else None,
        refund_amount=refund,
        refund_status=refund_status,
        method=method if refund > 0 else "",
        paid_to=(paid_to or "")[:100] if refund > 0 else "",
        reference=(reference or "").strip()[:100] if sent else "",
        sent_on=sent_on if sent else None,
        notes=(notes or "").strip(),
        created_by=user,
        approved_by=user,
        approved_at=now,
        approval_mode="owner_self",
        sent_recorded_by=user if sent else None,
        sent_recorded_at=now if sent else None,
    )
    DepositDeduction.objects.bulk_create(
        DepositDeduction(settlement=settlement, **line) for line in lines
    )

    unpaid = next((d for d in lines if d["kind"] == DeductionKind.UNPAID_BALANCE), None)
    if unpaid is not None:
        settlement.credit = credits.issue_credit(
            tenant=tenant,
            reason=CreditReason.DEPOSIT_APPLIED,
            net_amount=unpaid["amount"],
            credit_date=settlement_date,
            description=f"Security deposit applied to your balance ({settlement.number})",
            reference=settlement.number,
            actor=actor,
            today=today,
        )
        settlement.save(update_fields=["credit"])

    post_deposit_settlement(settlement)
    if sent:
        post_deposit_settlement_refund(settlement)

    tenant.deposit_refund_amount = refund
    tenant.deposit_refund_percentage = (refund / held * HUNDRED).quantize(CENTS, rounding=ROUND_HALF_UP)
    tenant.save(update_fields=["deposit_refund_amount", "deposit_refund_percentage", "updated_at"])

    audit.record(
        actor=actor,
        action="tenant.deposit_settle",
        object_type="deposit_settlement",
        object_id=settlement.pk,
        summary=(
            f"{settlement.number}: deposit of KES {held} for {tenant} settled — "
            f"KES {total} kept, KES {refund} to refund"
        ),
        new_values={
            "number": settlement.number,
            "tenant_id": tenant.pk,
            "settlement_date": settlement_date,
            "deposit_held": held,
            "balance_owed": owed,
            "deductions": [
                {
                    "kind": d["kind"], "description": d["description"], "amount": d["amount"],
                    "expense_category_id": d["expense_category"].pk if d["expense_category"] else None,
                }
                for d in lines
            ],
            "refund_basis": basis,
            "refund_percentage": settlement.refund_percentage,
            "refund_amount": refund,
            "refund_status": refund_status,
            "credit": settlement.credit.number if settlement.credit_id else None,
            "approval_mode": settlement.approval_mode,
        },
    )
    return settlement


def _lock(settlement: DepositSettlement) -> DepositSettlement:
    credits._lock_tenant(settlement.tenant)
    return DepositSettlement.objects.select_for_update().get(pk=settlement.pk)


@transaction.atomic
def mark_refund_sent(
    settlement: DepositSettlement,
    *,
    sent_on: _dt.date,
    method: str,
    reference: str = "",
    paid_to: str | None = None,
    actor=None,
    today: _dt.date | None = None,
) -> DepositSettlement:
    """The deposit refund has left: record it and post it."""
    from apps.ledger.posting import post_deposit_settlement_refund

    today = credits._today(today)
    settlement = _lock(settlement)
    if settlement.is_void:
        raise CreditError("This settlement has been voided.")
    if settlement.refund_status != DepositRefundStatus.TO_SEND:
        raise CreditError("Only a refund that is still to be sent can be marked as sent.")
    try:
        settlement.method = PaymentSource(method)
    except ValueError:
        raise CreditError("Choose how the money was sent.") from None
    settlement.reference = (reference or "").strip()[:100]
    credits._validate_sent(settlement.method, settlement.reference, sent_on, today)
    if sent_on < settlement.settlement_date:
        raise CreditError("The refund cannot have been sent before the deposit was settled.")
    if paid_to is not None:
        settlement.paid_to = paid_to[:100]

    settlement.refund_status = DepositRefundStatus.SENT
    settlement.sent_on = sent_on
    settlement.sent_recorded_by = credits._actor(actor)
    settlement.sent_recorded_at = timezone.now()
    settlement.save(update_fields=[
        "refund_status", "sent_on", "method", "paid_to", "reference",
        "sent_recorded_by", "sent_recorded_at",
    ])
    post_deposit_settlement_refund(settlement)

    audit.record(
        actor=actor,
        action="tenant.deposit_refund_sent",
        object_type="deposit_settlement",
        object_id=settlement.pk,
        summary=(
            f"{settlement.number}: deposit refund of KES {settlement.refund_amount} sent by "
            f"{settlement.get_method_display()}"
            + (f" ref {settlement.reference}" if settlement.reference else "")
        ),
        old_values={"refund_status": DepositRefundStatus.TO_SEND},
        new_values={
            "refund_status": DepositRefundStatus.SENT, "sent_on": sent_on,
            "reference": settlement.reference,
        },
    )
    return settlement


@transaction.atomic
def void_settlement(
    settlement: DepositSettlement, *, reason: str, actor=None, today: _dt.date | None = None,
) -> DepositSettlement:
    """Undo a settlement made in error, so the deposit can be settled again.

    The deposit goes back to being held in full: the credit it raised is voided
    (re-opening the rent it settled) and the deductions are reversed, dated
    today. A refund that has already been sent cannot be undone here — the
    money has left.
    """
    from apps.ledger.posting import reverse_deposit_settlement

    today = credits._today(today)
    reason = (reason or "").strip()
    if not reason:
        raise CreditError("Give a reason for voiding this settlement.")
    settlement = _lock(settlement)
    if settlement.is_void:
        raise CreditError("This settlement is already void.")
    if settlement.refund_status == DepositRefundStatus.SENT:
        raise CreditError(
            "The refund has already been sent, so this settlement can no longer be voided."
        )

    if settlement.credit_id and not settlement.credit.is_void:
        credits.void_credit(
            settlement.credit, reason=f"Deposit settlement {settlement.number} voided: {reason}",
            actor=actor, today=today, _settlement=True,
        )
    settlement.voided_at = timezone.now()
    settlement.voided_by = credits._actor(actor)
    settlement.void_reason = reason[:255]
    settlement.save(update_fields=["voided_at", "voided_by", "void_reason"])
    reverse_deposit_settlement(settlement, on=today)

    tenant = settlement.tenant
    tenant.deposit_refund_amount = None
    tenant.deposit_refund_percentage = HUNDRED
    tenant.save(update_fields=["deposit_refund_amount", "deposit_refund_percentage", "updated_at"])

    audit.record(
        actor=actor,
        action="tenant.deposit_settlement_void",
        object_type="deposit_settlement",
        object_id=settlement.pk,
        summary=f"{settlement.number}: voided — {reason}",
        old_values={"refund_status": settlement.refund_status},
        new_values={"void_reason": settlement.void_reason},
    )
    return settlement
