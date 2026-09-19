"""
Tenant credits and refunds — the one place they are created or changed.

Every function here is atomic, locks the tenant first (so two clicks can never
use the same credit twice), posts its journal entry STRICTLY — if the ledger
refuses the entry the whole action rolls back, because a credit that is on the
tenant's account but not in the books is exactly the drift this exists to stop
— and writes a FinancialAuditLog row.

Vocabulary, as the owner sees it on the tenant page:

    Add Credit            issue_credit
    Apply to Next Invoice set_hold(hold=False)   — the default for a new credit
    Hold Credit           set_hold(hold=True)
    Refund Credit         create_refund
    Mark as Sent          mark_refund_sent
    Cancel Refund         cancel_refund
    Void Credit / Refund  void_credit / void_refund

The accounting behind each is in ``apps.ledger.posting`` (tenant credits
section). Owner-only today: the owner both creates and approves, and the record
says so (``approval_mode="owner_self"``) so a second approver can be added
later without changing the data.
"""
from __future__ import annotations

import datetime as _dt
import logging
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from apps.accounts import audit

from .models import (
    CREDIT_TYPE_FOR_REASON,
    REFUND_ACTIVE_STATUSES,
    Arrears,
    CreditApplication,
    CreditApplicationOrigin,
    CreditReason,
    CreditStatus,
    CreditType,
    DocumentSequence,
    Payment,
    PaymentSource,
    PaymentType,
    Refund,
    RefundLine,
    RefundStatus,
    TenantCredit,
    UtilityCharge,
)

logger = logging.getLogger(__name__)

ZERO = Decimal("0.00")
CENTS = Decimal("0.01")

#: Document series. Credit notes get their own run of numbers because a VAT
#: credit note is a tax document in its own right.
SERIES_FOR_TYPE = {CreditType.CREDIT_NOTE: "CN", CreditType.ACCOUNT_CREDIT: "CR"}
REFUND_SERIES = "RF"

#: Reasons that must come with evidence (a receipt, the cutover record).
EVIDENCE_REQUIRED = {CreditReason.TENANT_PAID_COST, CreditReason.OPENING_CREDIT}

#: A reference is how an outgoing payment is traced on the bank statement;
#: cash handed over has none.
REFERENCE_REQUIRED_METHODS = {PaymentSource.MPESA, PaymentSource.BANK, PaymentSource.CHEQUE}


class CreditError(Exception):
    """A credit or refund that cannot be done as asked. The message is for the owner."""


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _money(value) -> Decimal:
    try:
        return Decimal(str(value)).quantize(CENTS)
    except (InvalidOperation, TypeError, ValueError):
        raise CreditError("Enter the amount as a number, e.g. 5000.") from None


def _actor(actor):
    return actor if getattr(actor, "is_authenticated", False) else None


def _lock_tenant(tenant):
    from apps.tenants.models import Tenant

    Tenant.objects.select_for_update().filter(pk=tenant.pk).first()


def _next_number(series: str) -> str:
    """Next number in a series, under a row lock so two documents never share one."""
    seq, _ = DocumentSequence.objects.select_for_update().get_or_create(name=series)
    seq.last += 1
    seq.save(update_fields=["last"])
    return f"{series}-{seq.last:05d}"


def _today(today=None) -> _dt.date:
    return today or timezone.localdate()


def _refresh_unit_status(arrears: Arrears, today: _dt.date) -> None:
    """Keep the unit board in step when the current month's cover changes.

    Same rule the waiver and payment paths follow: only the live month moves
    the unit, so settling an old period never disturbs it.
    """
    if arrears.period_month == today.month and arrears.period_year == today.year:
        from apps.buildings.services import recalculate_unit_status

        recalculate_unit_status(
            arrears.tenant.unit, arrears.covered, obligation=arrears.expected_total
        )


def _resettle(arrears: Arrears) -> None:
    arrears.balance = max(arrears.expected_total - arrears.covered, ZERO)
    arrears.is_cleared = arrears.covered >= arrears.expected_total
    arrears.save(update_fields=["credit_applied", "balance", "is_cleared", "updated_at"])


# ---------------------------------------------------------------------------
# where a tenant stands
# ---------------------------------------------------------------------------

def manual_credit_available(tenant, *, include_held: bool = True) -> Decimal:
    """What is left on the tenant's issued credits."""
    qs = TenantCredit.objects.filter(tenant=tenant, status=CreditStatus.ISSUED)
    if not include_held:
        qs = qs.filter(on_hold=False)
    return sum((c.remaining for c in qs), ZERO)


def account_balance(tenant) -> Decimal:
    """Everything raised to date, less everything received and credited, plus refunds sent.

    Unlike ``monthly_ledger.current_balance`` this counts a month already
    invoiced ahead — arcade rent is raised on the 25th for the month after, and
    a tenant who has paid it must not look in credit and be refunded rent they
    owe next week.
    """
    charged = Arrears.objects.filter(tenant=tenant).aggregate(
        rent=Sum("expected_rent"), vat=Sum("expected_vat"), waived=Sum("waived_amount"),
    )
    other = UtilityCharge.objects.filter(tenant=tenant).aggregate(t=Sum("amount"))["t"]
    received = (
        Payment.objects.filter(tenant=tenant, voided_at__isnull=True)
        .exclude(payment_type=PaymentType.DEPOSIT)
        .aggregate(t=Sum("amount"))["t"]
    )
    credited = TenantCredit.objects.filter(
        tenant=tenant, status=CreditStatus.ISSUED
    ).aggregate(t=Sum("amount"))["t"]
    refunded = Refund.objects.filter(
        tenant=tenant, status=RefundStatus.SENT
    ).aggregate(t=Sum("amount"))["t"]
    total = (
        (charged["rent"] or ZERO) + (charged["vat"] or ZERO) - (charged["waived"] or ZERO)
        + (other or ZERO) - (received or ZERO) - (credited or ZERO) + (refunded or ZERO)
    )
    return _money(total)


def scheduled_refunds(tenant) -> Decimal:
    return _money(
        Refund.objects.filter(tenant=tenant, status=RefundStatus.SCHEDULED)
        .aggregate(t=Sum("amount"))["t"] or ZERO
    )


def refundable_amount(tenant) -> Decimal:
    """How much can be refunded now.

    The lesser of what the tenant is genuinely in credit by — across rent,
    water and anything already invoiced ahead, less refunds still to be sent —
    and what their credits and overpaid rent actually hold. A tenant who owes
    anything anywhere has nothing to refund.
    """
    from .services import available_credit

    in_credit = max(-account_balance(tenant), ZERO) - scheduled_refunds(tenant)
    sources = available_credit(tenant) + manual_credit_available(tenant)
    return _money(max(min(in_credit, sources), ZERO))


def credit_position(tenant) -> dict:
    """Everything the tenant page's Balance card and Credits panel need."""
    from .monthly_ledger import current_balance
    from .services import available_credit

    balance = current_balance(tenant, today=timezone.localdate())
    return {
        "balance": _money(balance),
        "credit_on_account": _money(max(-balance, ZERO)),
        "overpayment_credit": _money(available_credit(tenant)),
        "credits_available": _money(manual_credit_available(tenant, include_held=False)),
        "credits_held": _money(
            manual_credit_available(tenant) - manual_credit_available(tenant, include_held=False)
        ),
        "refunds_to_send": scheduled_refunds(tenant),
        "refundable": refundable_amount(tenant),
    }


# ---------------------------------------------------------------------------
# Add Credit
# ---------------------------------------------------------------------------

def creditable_remaining(*, arrears: Arrears | None = None, utility_charge: UtilityCharge | None = None) -> Decimal:
    """How much of a charge (before VAT) can still be credited back."""
    if arrears is not None:
        base = arrears.expected_rent or ZERO
        already = arrears.credit_notes.filter(status=CreditStatus.ISSUED)
    else:
        base = utility_charge.amount or ZERO
        already = utility_charge.credit_notes.filter(status=CreditStatus.ISSUED)
    used = already.aggregate(t=Sum("net_amount"))["t"] or ZERO
    return _money(max(base - used, ZERO))


def vat_on_credit(arrears: Arrears | None, net: Decimal) -> Decimal:
    """The VAT that comes back with a credit note — the charge's own rate, if it had one."""
    if arrears is None or not arrears.expected_vat or not arrears.expected_rent:
        return ZERO
    return _money(net * arrears.expected_vat / arrears.expected_rent)


def _validate_links(tenant, reason, *, arrears, utility_charge, expense_category, evidence):
    from .monthly_ledger import OPENING_MARKER

    if CREDIT_TYPE_FOR_REASON[reason] == CreditType.CREDIT_NOTE:
        if expense_category is not None:
            raise CreditError("A credit note corrects a charge; it has no expense category.")
        if reason == CreditReason.RENT_CONCESSION and (arrears is None or utility_charge is not None):
            raise CreditError("Choose the month's rent the discount is for.")
        if (arrears is None) == (utility_charge is None):
            raise CreditError("Choose the one charge this credit corrects.")
        if arrears is not None:
            if arrears.tenant_id != tenant.pk:
                raise CreditError("That rent charge belongs to a different tenant.")
            if OPENING_MARKER in (arrears.waive_notes or ""):
                raise CreditError(
                    "A balance brought forward is not a charge that can be corrected here. "
                    "Use 'Credit owed from before the system' instead."
                )
        if utility_charge is not None:
            if utility_charge.tenant_id != tenant.pk:
                raise CreditError("That charge belongs to a different tenant.")
            if utility_charge.amount <= 0:
                raise CreditError("That entry is already a credit, not a charge.")
    else:
        if arrears is not None or utility_charge is not None:
            raise CreditError("Only a billing correction or a rent discount is tied to a charge.")
        if reason == CreditReason.TENANT_PAID_COST:
            if expense_category is None or not expense_category.account_id:
                raise CreditError("Choose what kind of cost the tenant paid for.")
        elif expense_category is not None:
            raise CreditError("An expense category only applies to a cost the tenant paid for.")
    if reason in EVIDENCE_REQUIRED and not evidence:
        raise CreditError("Attach the supporting document for this kind of credit.")


@transaction.atomic
def issue_credit(
    *,
    tenant,
    reason: str,
    net_amount,
    credit_date: _dt.date,
    description: str,
    actor=None,
    internal_notes: str = "",
    reference: str = "",
    arrears: Arrears | None = None,
    utility_charge: UtilityCharge | None = None,
    expense_category=None,
    evidence=None,
    evidence_name: str = "",
    hold: bool = False,
    today: _dt.date | None = None,
) -> TenantCredit:
    """Add a credit to a tenant's account: number it, post it, audit it, and —
    unless it is held — use it straight away on anything the tenant owes.
    """
    from apps.ledger.posting import post_tenant_credit

    today = _today(today)
    _lock_tenant(tenant)

    try:
        reason = CreditReason(reason)
    except ValueError:
        raise CreditError("Choose why the tenant is getting this credit.") from None
    net = _money(net_amount)
    if net <= 0:
        raise CreditError("The amount must be more than zero.")
    if credit_date > today:
        raise CreditError("A credit cannot be dated in the future.")
    description = (description or "").strip()
    if not description:
        raise CreditError("Explain the credit — the explanation is printed on the tenant's statement.")

    _validate_links(
        tenant, reason, arrears=arrears, utility_charge=utility_charge,
        expense_category=expense_category, evidence=evidence,
    )

    vat = ZERO
    if arrears is not None or utility_charge is not None:
        if arrears is not None:
            arrears = Arrears.objects.select_for_update().get(pk=arrears.pk)
        cap = creditable_remaining(arrears=arrears, utility_charge=utility_charge)
        if net > cap:
            raise CreditError(
                f"Only KES {cap:,.2f} of that charge can still be credited "
                f"(before VAT)."
            )
        vat = vat_on_credit(arrears, net)

    credit_type = CREDIT_TYPE_FOR_REASON[reason]
    user = _actor(actor)
    now = timezone.now()
    credit = TenantCredit(
        number=_next_number(SERIES_FOR_TYPE[credit_type]),
        tenant=tenant,
        credit_type=credit_type,
        reason=reason,
        credit_date=credit_date,
        net_amount=net,
        vat_amount=vat,
        amount=net + vat,
        arrears=arrears,
        utility_charge=utility_charge,
        expense_category=expense_category,
        description=description[:200],
        internal_notes=internal_notes or "",
        reference=(reference or "")[:100],
        evidence_name=(evidence_name or "")[:255],
        on_hold=bool(hold),
        created_by=user,
        approved_by=user,
        approved_at=now,
        approval_mode="owner_self",
    )
    if evidence:
        credit.evidence = evidence
    credit.save()

    post_tenant_credit(credit)

    audit.record(
        actor=actor,
        action="credit.issue",
        object_type="tenant_credit",
        object_id=credit.pk,
        summary=f"{credit.number}: credit of KES {credit.amount} to {tenant} — {credit.get_reason_display()}",
        new_values={
            "number": credit.number,
            "tenant_id": tenant.pk,
            "reason": credit.reason,
            "credit_date": credit.credit_date,
            "net_amount": credit.net_amount,
            "vat_amount": credit.vat_amount,
            "amount": credit.amount,
            "description": credit.description,
            "reference": credit.reference,
            "arrears_id": credit.arrears_id,
            "utility_charge_id": credit.utility_charge_id,
            "expense_category_id": credit.expense_category_id,
            "evidence": credit.evidence_name,
            "on_hold": credit.on_hold,
            "approval_mode": credit.approval_mode,
        },
    )

    if not credit.on_hold:
        _apply_to_open_rent(credit, origin=CreditApplicationOrigin.ON_ISSUE, actor=actor, on=today)
        credit.refresh_from_db()
    return credit


# ---------------------------------------------------------------------------
# Applying credit to rent
# ---------------------------------------------------------------------------

def _apply(credit: TenantCredit, arrears: Arrears, amount: Decimal, *, origin, actor, on) -> CreditApplication:
    from apps.ledger.posting import post_credit_application

    application = CreditApplication.objects.create(
        credit=credit, arrears=arrears, amount=amount, applied_on=on,
        origin=origin, created_by=_actor(actor),
    )
    arrears.credit_applied = (arrears.credit_applied or ZERO) + amount
    _resettle(arrears)
    credit.amount_applied = credit.amount_applied + amount
    credit.save(update_fields=["amount_applied"])

    post_credit_application(application)
    _refresh_unit_status(arrears, on)

    audit.record(
        actor=actor,
        action="credit.apply",
        object_type="tenant_credit",
        object_id=credit.pk,
        summary=(
            f"{credit.number}: KES {amount} applied to "
            f"{arrears.period_month}/{arrears.period_year} rent"
            + (" (billing run)" if origin == CreditApplicationOrigin.BILLING else "")
        ),
        new_values={
            "application_id": application.pk,
            "arrears_id": arrears.pk,
            "amount": amount,
            "origin": origin,
            "arrears_balance": arrears.balance,
        },
    )
    return application


def _open_rent(tenant, *, first: Arrears | None = None):
    """Rent the tenant still owes, the corrected month first, then oldest first."""
    rows = list(
        Arrears.objects.select_for_update()
        .filter(tenant=tenant, balance__gt=0)
        .order_by("period_year", "period_month")
    )
    if first is not None:
        rows.sort(key=lambda r: r.pk != first.pk)
    return rows


def _apply_to_open_rent(credit: TenantCredit, *, origin, actor, on) -> list[CreditApplication]:
    applied = []
    for arrears in _open_rent(credit.tenant, first=credit.arrears):
        remaining = credit.remaining
        if remaining <= 0:
            break
        applied.append(
            _apply(credit, arrears, min(remaining, arrears.balance), origin=origin, actor=actor, on=on)
        )
    return applied


@transaction.atomic
def apply_account_credits(arrears: Arrears, *, today: _dt.date | None = None) -> Decimal:
    """Settle a newly raised month from the tenant's issued, un-held credits.

    Called by the monthly billing run after overpaid rent has been applied
    (``services.apply_available_credit``). Oldest credit first. Returns the
    amount applied.
    """
    today = _today(today)
    _lock_tenant(arrears.tenant)
    arrears = Arrears.objects.select_for_update().get(pk=arrears.pk)
    total = ZERO
    credits = (
        TenantCredit.objects.select_for_update()
        .filter(tenant_id=arrears.tenant_id, status=CreditStatus.ISSUED, on_hold=False)
        .order_by("credit_date", "id")
    )
    for credit in credits:
        if arrears.balance <= 0:
            break
        remaining = credit.remaining
        if remaining <= 0:
            continue
        amount = min(remaining, arrears.balance)
        _apply(credit, arrears, amount, origin=CreditApplicationOrigin.BILLING, actor=None, on=today)
        total += amount
    return total


@transaction.atomic
def set_hold(credit: TenantCredit, *, hold: bool, actor=None, today: _dt.date | None = None) -> TenantCredit:
    """Hold Credit / Apply to Next Invoice.

    Releasing a hold also uses the credit at once on anything already owed —
    "apply to next invoice" should never leave a tenant in arrears while their
    own credit sits unused beside it.
    """
    today = _today(today)
    _lock_tenant(credit.tenant)
    credit = TenantCredit.objects.select_for_update().get(pk=credit.pk)
    if credit.is_void:
        raise CreditError("This credit has been voided.")
    if credit.on_hold == hold:
        return credit
    credit.on_hold = hold
    credit.save(update_fields=["on_hold"])
    audit.record(
        actor=actor,
        action="credit.hold" if hold else "credit.release",
        object_type="tenant_credit",
        object_id=credit.pk,
        summary=f"{credit.number}: " + ("held — not applied automatically" if hold else "set to apply to next invoice"),
        old_values={"on_hold": not hold},
        new_values={"on_hold": hold},
    )
    if not hold:
        _apply_to_open_rent(credit, origin=CreditApplicationOrigin.OWNER, actor=actor, on=today)
        credit.refresh_from_db()
    return credit


def _unapply(application: CreditApplication, *, reason: str, actor, on) -> None:
    from apps.ledger.posting import reverse_credit_application

    arrears = Arrears.objects.select_for_update().get(pk=application.arrears_id)
    arrears.credit_applied = max((arrears.credit_applied or ZERO) - application.amount, ZERO)
    _resettle(arrears)

    credit = application.credit
    credit.amount_applied = max(credit.amount_applied - application.amount, ZERO)
    credit.save(update_fields=["amount_applied"])

    application.reversed_at = timezone.now()
    application.reversed_by = _actor(actor)
    application.reverse_reason = reason[:255]
    application.save(update_fields=["reversed_at", "reversed_by", "reverse_reason"])

    reverse_credit_application(application, on=on)
    _refresh_unit_status(arrears, on)


# ---------------------------------------------------------------------------
# Void Credit
# ---------------------------------------------------------------------------

def void_preview(credit: TenantCredit) -> dict:
    """What voiding would do, in figures the confirmation dialog can state."""
    applications = list(credit.applications.filter(reversed_at__isnull=True).select_related("arrears"))
    refunded_sent = credit.refund_lines.filter(refund__status=RefundStatus.SENT).aggregate(
        t=Sum("amount"))["t"] or ZERO
    scheduled = credit.refund_lines.filter(refund__status=RefundStatus.SCHEDULED).aggregate(
        t=Sum("amount"))["t"] or ZERO
    return {
        "reopened": [
            {"period_month": a.arrears.period_month, "period_year": a.arrears.period_year, "amount": a.amount}
            for a in applications
        ],
        "reopened_total": _money(sum((a.amount for a in applications), ZERO)),
        "refunded_kept": _money(refunded_sent),
        "refunds_cancelled": _money(scheduled),
        "tenant_will_owe_more_by": _money(sum((a.amount for a in applications), ZERO) + refunded_sent),
    }


@transaction.atomic
def void_credit(credit: TenantCredit, *, reason: str, actor=None, today: _dt.date | None = None) -> TenantCredit:
    """Take a credit off the account for good.

    * Rent it settled is re-opened (the applications are reversed).
    * A refund still to be sent from it is cancelled.
    * A refund already sent stays — the money left — so the tenant now owes it.
    * A mirror-image journal entry is posted, dated today.
    """
    from apps.ledger.posting import reverse_tenant_credit

    today = _today(today)
    reason = (reason or "").strip()
    if not reason:
        raise CreditError("Give a reason for voiding this credit.")
    _lock_tenant(credit.tenant)
    credit = TenantCredit.objects.select_for_update().get(pk=credit.pk)
    if credit.is_void:
        raise CreditError("This credit is already void.")

    preview = void_preview(credit)
    for refund in Refund.objects.filter(
        lines__credit=credit, status=RefundStatus.SCHEDULED
    ).distinct():
        cancel_refund(refund, reason=f"Credit {credit.number} voided: {reason}", actor=actor)

    credit.refresh_from_db()
    for application in credit.applications.filter(reversed_at__isnull=True):
        _unapply(application, reason=f"Credit voided: {reason}", actor=actor, on=today)

    credit.refresh_from_db()
    credit.status = CreditStatus.VOID
    credit.voided_at = timezone.now()
    credit.voided_by = _actor(actor)
    credit.void_reason = reason[:255]
    credit.save(update_fields=["status", "voided_at", "voided_by", "void_reason"])

    reverse_tenant_credit(credit, on=today)

    audit.record(
        actor=actor,
        action="credit.void",
        object_type="tenant_credit",
        object_id=credit.pk,
        summary=f"{credit.number}: voided — {reason}",
        old_values={"status": CreditStatus.ISSUED, "amount": credit.amount},
        new_values={
            "status": CreditStatus.VOID,
            "void_reason": credit.void_reason,
            "rent_reopened": preview["reopened_total"],
            "refunded_kept": preview["refunded_kept"],
            "refunds_cancelled": preview["refunds_cancelled"],
        },
    )
    return credit


# ---------------------------------------------------------------------------
# Refund Credit
# ---------------------------------------------------------------------------

def _draw_plan(tenant, amount: Decimal, credit: TenantCredit | None):
    """Which credit (or overpaid rent) each shilling of a refund comes out of."""
    from .services import available_credit

    if credit is not None:
        return [(credit, amount)]
    plan, left = [], amount
    overpaid = available_credit(tenant)
    if overpaid > 0:
        take = min(overpaid, left)
        plan.append((None, take))
        left -= take
    for c in (
        TenantCredit.objects.select_for_update()
        .filter(tenant=tenant, status=CreditStatus.ISSUED)
        .order_by("credit_date", "id")
    ):
        if left <= 0:
            break
        take = min(c.remaining, left)
        if take > 0:
            plan.append((c, take))
            left -= take
    if left > 0:
        raise CreditError("There is not enough credit on the account for that refund.")
    return plan


def _validate_sent(method: str, reference: str, sent_on: _dt.date, today: _dt.date) -> None:
    if sent_on > today:
        raise CreditError("The date the money was sent cannot be in the future.")
    if method in REFERENCE_REQUIRED_METHODS and not (reference or "").strip():
        raise CreditError("Enter the transaction reference of the money you sent.")


@transaction.atomic
def create_refund(
    *,
    tenant,
    amount,
    method: str,
    actor=None,
    paid_to: str = "",
    reference: str = "",
    notes: str = "",
    sent_on: _dt.date | None = None,
    credit: TenantCredit | None = None,
    today: _dt.date | None = None,
) -> Refund:
    """Refund Credit. With ``sent_on`` the money has gone and it posts now;
    without, the amount is set aside as a refund to send.
    """
    from apps.ledger.posting import post_refund

    today = _today(today)
    _lock_tenant(tenant)
    amount = _money(amount)
    if amount <= 0:
        raise CreditError("The refund must be more than zero.")
    try:
        method = PaymentSource(method)
    except ValueError:
        raise CreditError("Choose how the money is being sent.") from None
    if sent_on is not None:
        _validate_sent(method, reference, sent_on, today)

    if credit is not None:
        credit = TenantCredit.objects.select_for_update().get(pk=credit.pk)
        if credit.tenant_id != tenant.pk:
            raise CreditError("That credit belongs to a different tenant.")
        if credit.is_void:
            raise CreditError("That credit has been voided.")
        if amount > credit.remaining:
            raise CreditError(f"Only KES {credit.remaining:,.2f} is left on {credit.number}.")

    refundable = refundable_amount(tenant)
    if amount > refundable:
        if refundable <= 0:
            raise CreditError(
                "Nothing can be refunded: the tenant is not in credit once everything "
                "they owe (including rent already invoiced) is counted."
            )
        raise CreditError(f"Only KES {refundable:,.2f} can be refunded right now.")

    plan = _draw_plan(tenant, amount, credit)
    user = _actor(actor)
    now = timezone.now()
    sent = sent_on is not None
    refund = Refund.objects.create(
        number=_next_number(REFUND_SERIES),
        tenant=tenant,
        amount=amount,
        method=method,
        paid_to=(paid_to or "")[:100],
        reference=(reference or "").strip()[:100],
        notes=(notes or "")[:255],
        status=RefundStatus.SENT if sent else RefundStatus.SCHEDULED,
        sent_on=sent_on,
        unit_classification=tenant.unit.classification,
        created_by=user,
        approved_by=user,
        approved_at=now,
        approval_mode="owner_self",
        sent_recorded_by=user if sent else None,
        sent_recorded_at=now if sent else None,
    )
    for source, take in plan:
        RefundLine.objects.create(refund=refund, credit=source, amount=take)
        if source is not None:
            source.amount_refunded = source.amount_refunded + take
            source.save(update_fields=["amount_refunded"])

    if sent:
        post_refund(refund)

    audit.record(
        actor=actor,
        action="refund.record" if sent else "refund.schedule",
        object_type="refund",
        object_id=refund.pk,
        summary=(
            f"{refund.number}: KES {amount} to {tenant} by {refund.get_method_display()}"
            + (f" ref {refund.reference}" if refund.reference else "")
            + ("" if sent else " — to send")
        ),
        new_values={
            "number": refund.number,
            "tenant_id": tenant.pk,
            "amount": amount,
            "method": method,
            "paid_to": refund.paid_to,
            "reference": refund.reference,
            "sent_on": sent_on,
            "drawn_from": [
                {"credit": s.number if s is not None else "overpayment", "amount": t} for s, t in plan
            ],
            "approval_mode": refund.approval_mode,
        },
    )
    return refund


def _lock_refund(refund: Refund) -> Refund:
    _lock_tenant(refund.tenant)
    return Refund.objects.select_for_update().get(pk=refund.pk)


@transaction.atomic
def mark_refund_sent(
    refund: Refund,
    *,
    sent_on: _dt.date,
    reference: str = "",
    method: str | None = None,
    paid_to: str | None = None,
    actor=None,
    today: _dt.date | None = None,
) -> Refund:
    """Mark as Sent: the money has now left, so the refund posts."""
    from apps.ledger.posting import post_refund

    today = _today(today)
    refund = _lock_refund(refund)
    if refund.status != RefundStatus.SCHEDULED:
        raise CreditError("Only a refund that is still to be sent can be marked as sent.")
    if method:
        try:
            refund.method = PaymentSource(method)
        except ValueError:
            raise CreditError("Choose how the money was sent.") from None
    if paid_to is not None:
        refund.paid_to = paid_to[:100]
    refund.reference = (reference or refund.reference or "").strip()[:100]
    _validate_sent(refund.method, refund.reference, sent_on, today)

    refund.status = RefundStatus.SENT
    refund.sent_on = sent_on
    refund.sent_recorded_by = _actor(actor)
    refund.sent_recorded_at = timezone.now()
    refund.save(update_fields=[
        "status", "sent_on", "method", "paid_to", "reference", "sent_recorded_by", "sent_recorded_at",
    ])
    post_refund(refund)

    audit.record(
        actor=actor,
        action="refund.mark_sent",
        object_type="refund",
        object_id=refund.pk,
        summary=f"{refund.number}: KES {refund.amount} sent by {refund.get_method_display()} ref {refund.reference}",
        old_values={"status": RefundStatus.SCHEDULED},
        new_values={"status": RefundStatus.SENT, "sent_on": sent_on, "reference": refund.reference},
    )
    return refund


def _release_lines(refund: Refund) -> None:
    """Give a refund's amount back to the credits it was drawn from."""
    for line in refund.lines.select_related("credit"):
        if line.credit_id:
            credit = TenantCredit.objects.select_for_update().get(pk=line.credit_id)
            credit.amount_refunded = max(credit.amount_refunded - line.amount, ZERO)
            credit.save(update_fields=["amount_refunded"])


@transaction.atomic
def cancel_refund(refund: Refund, *, reason: str, actor=None) -> Refund:
    """Cancel a refund that was never sent. Nothing was posted, so nothing reverses."""
    reason = (reason or "").strip()
    if not reason:
        raise CreditError("Give a reason for cancelling this refund.")
    refund = _lock_refund(refund)
    if refund.status != RefundStatus.SCHEDULED:
        raise CreditError("Only a refund that is still to be sent can be cancelled.")
    _release_lines(refund)
    refund.status = RefundStatus.CANCELLED
    refund.closed_at = timezone.now()
    refund.closed_by = _actor(actor)
    refund.close_reason = reason[:255]
    refund.save(update_fields=["status", "closed_at", "closed_by", "close_reason"])
    audit.record(
        actor=actor,
        action="refund.cancel",
        object_type="refund",
        object_id=refund.pk,
        summary=f"{refund.number}: cancelled before sending — {reason}",
        old_values={"status": RefundStatus.SCHEDULED},
        new_values={"status": RefundStatus.CANCELLED, "reason": refund.close_reason},
    )
    return refund


@transaction.atomic
def void_refund(refund: Refund, *, reason: str, actor=None, today: _dt.date | None = None) -> Refund:
    """Void a sent refund that never reached the tenant or came back.

    The credit it drew on is available again, and a mirror-image entry is
    posted, dated today.
    """
    from apps.ledger.posting import reverse_refund

    today = _today(today)
    reason = (reason or "").strip()
    if not reason:
        raise CreditError("Give a reason for voiding this refund.")
    refund = _lock_refund(refund)
    if refund.status != RefundStatus.SENT:
        raise CreditError("Only a refund that was sent can be voided. Cancel one that is still to be sent.")
    _release_lines(refund)
    refund.status = RefundStatus.VOID
    refund.closed_at = timezone.now()
    refund.closed_by = _actor(actor)
    refund.close_reason = reason[:255]
    refund.save(update_fields=["status", "closed_at", "closed_by", "close_reason"])
    reverse_refund(refund, on=today)
    audit.record(
        actor=actor,
        action="refund.void",
        object_type="refund",
        object_id=refund.pk,
        summary=f"{refund.number}: voided — {reason}",
        old_values={"status": RefundStatus.SENT},
        new_values={"status": RefundStatus.VOID, "reason": refund.close_reason},
    )
    return refund


# ---------------------------------------------------------------------------
# Readers used by the balance, statement and aging code
# ---------------------------------------------------------------------------

def issued_credits(tenant_ids):
    """Credits that count toward a balance: issued, not void."""
    return TenantCredit.objects.filter(tenant_id__in=tenant_ids, status=CreditStatus.ISSUED)


def sent_refunds(tenant_ids):
    """Refunds that count toward a balance: the money actually left."""
    return Refund.objects.filter(tenant_id__in=tenant_ids, status=RefundStatus.SENT)


def active_refund_lines_q() -> Q:
    return Q(refund__status__in=REFUND_ACTIVE_STATUSES)
