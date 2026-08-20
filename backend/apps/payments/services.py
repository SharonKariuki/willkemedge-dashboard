"""
Payment processing service.

Records a payment, creates an immutable Transaction (with tax applied via
tax_service), updates/creates the arrears record for the period, and
recalculates the tenant's unit status.

Tax logic lives exclusively in tax_service.py — this module never hardcodes
rates or classification rules.
"""
import uuid
from decimal import Decimal

from django.db import IntegrityError, models, transaction
from django.utils import timezone

from apps.buildings.models import UnitClassification
from apps.buildings.services import recalculate_unit_status

from .models import Arrears, Payment, PaymentMode, PaymentType, Transaction
from .tax_service import calculate_tax, split_tax_inclusive

ZERO = Decimal("0")

#: Only rent discharges a rent obligation. A security deposit is a refundable
#: liability and a late fee is separate income — neither is rent, and counting
#: them used to mark a tenant's rent "paid" when no rent had been received.
SETTLES_RENT = (PaymentType.RENT,)


class IdempotencyConflict(Exception):
    """A replayed idempotency key describes a *different* payment.

    Raised instead of silently returning the stored record, which used to hand
    tenant B a `201 Created` carrying tenant A's payment while B's cash was
    never recorded at all.
    """

    def __init__(self, existing: Payment, message: str):
        self.existing = existing
        super().__init__(message)


def _generate_transaction_id() -> str:
    """Return a unique, traceable transaction ID: TXN-<16 hex chars>."""
    return f"TXN-{uuid.uuid4().hex[:16].upper()}"


def expected_vat_for(tenant, base_rent: Decimal) -> Decimal:
    """VAT owed on top of a BUSINESS unit's base rent; zero for residential.

    `Tenant.monthly_rent` / `Arrears.expected_rent` hold the VAT-EXCLUSIVE rent
    for commercial units (see import_matasia), while cash received is
    VAT-INCLUSIVE. This is the bridge between the two.
    """
    base = Decimal(str(base_rent or 0))
    if base <= 0:
        return ZERO
    classification = getattr(getattr(tenant, "unit", None), "classification", None)
    if classification != UnitClassification.BUSINESS:
        return ZERO
    return calculate_tax(base, UnitClassification.BUSINESS).tax_amount


def rent_payments_for(tenant, period_month: int, period_year: int):
    """Live (non-void) rent payments that settle one period's obligation."""
    return Payment.objects.filter(
        tenant=tenant,
        period_month=period_month,
        period_year=period_year,
        payment_type__in=SETTLES_RENT,
        voided_at__isnull=True,
    )


def _source_to_payment_mode(source: str) -> str:
    """Map PaymentSource values to PaymentMode values (case-insensitive)."""
    mapping = {
        "mpesa": PaymentMode.MPESA,
        "bank": PaymentMode.BANK,
        "cash": PaymentMode.CASH,
        "cheque": PaymentMode.CHEQUE,
    }
    return mapping.get(source.lower(), PaymentMode.CASH)


def process_payment(
    *,
    tenant,
    amount: Decimal,
    payment_date,
    period_month: int,
    period_year: int,
    source: str = "cash",
    reference: str = "",
    notes: str = "",
    idempotency_key: str = "",
    payment_type: str = PaymentType.RENT,
    created_by=None,
) -> Payment:
    """
    Record a payment, compute VAT, persist a Transaction, and update arrears.

    Flow
    ----
    1. Read unit.classification from the tenant's current unit.
    2. Run calculate_tax(base_amount, classification) — no rates hardcoded here.
    3. Create immutable Payment record (base amount, as before).
    4. Create immutable Transaction record (all tax fields stored at write time).
    5. Update/create Arrears for the period.
    6. Recalculate unit status.

    Returns the Payment instance (callers can follow .transaction for tax data).

    Idempotency
    -----------
    When ``idempotency_key`` is non-blank, this call is treated as a single,
    de-duplicated payment: a genuine re-submission with the same key returns the
    already-recorded Payment instead of double-booking (and double-reducing
    arrears). The key is scoped to the TENANT and enforced by a partial unique
    constraint at the DB level, so concurrent retries that both pass the
    pre-check are still caught via IntegrityError. FIFO allocation passes a
    per-chunk key derived from the bank transaction id (see
    `allocate_payment_fifo`), so a replayed credit is de-duplicated there too.

    A stored payment only counts as "the same payment" if the amount and date
    match too. Anything else is a key collision — two different receipts sharing
    a reference — and raises `IdempotencyConflict` rather than silently
    discarding the second one.
    """
    if idempotency_key:
        existing = _existing_for_key(tenant, idempotency_key, amount, payment_date)
        if existing:
            return existing
    try:
        return _process_payment_atomic(
            tenant=tenant,
            amount=amount,
            payment_date=payment_date,
            period_month=period_month,
            period_year=period_year,
            source=source,
            reference=reference,
            notes=notes,
            idempotency_key=idempotency_key,
            payment_type=payment_type,
            created_by=created_by,
        )
    except IntegrityError:
        # A concurrent retry won the race and inserted the row first; return it
        # rather than surfacing the constraint violation.
        if idempotency_key:
            existing = _existing_for_key(tenant, idempotency_key, amount, payment_date)
            if existing:
                return existing
        raise


def _existing_for_key(tenant, idempotency_key: str, amount, payment_date):
    """Return the already-recorded Payment for this key, or None.

    Raises IdempotencyConflict when a row exists under the key but describes a
    materially different payment.
    """
    existing = Payment.objects.filter(
        tenant=tenant, idempotency_key=idempotency_key
    ).first()
    if existing is None:
        return None
    if existing.amount != Decimal(str(amount)) or existing.payment_date != payment_date:
        raise IdempotencyConflict(
            existing,
            f"Reference already recorded for this tenant as KES {existing.amount} "
            f"on {existing.payment_date} (payment #{existing.pk}). Use a distinct "
            f"reference for a different payment.",
        )
    return existing


@transaction.atomic
def _process_payment_atomic(
    *,
    tenant,
    amount: Decimal,
    payment_date,
    period_month: int,
    period_year: int,
    source: str,
    reference: str,
    notes: str,
    idempotency_key: str,
    payment_type: str = PaymentType.RENT,
    created_by=None,
) -> Payment:
    unit = tenant.unit
    classification = unit.classification  # the trigger field

    # --- Tax split (centralised) ---
    # `amount` is the cash actually received. For commercial units that figure
    # is VAT-INCLUSIVE (rent + 16% paid as one), so VAT is split OUT of it — the
    # same treatment the ledger applies — never grossed up on top. Residential
    # is exempt (net == gross). Payment.amount stays the gross received so the
    # ledger and arrears (which read it) are consistent.
    gross = Decimal(str(amount))
    tax_result = split_tax_inclusive(gross, classification)

    # --- Immutable Payment (stores the gross cash received) ---
    payment = Payment.objects.create(
        tenant=tenant,
        amount=gross,
        payment_date=payment_date,
        period_month=period_month,
        period_year=period_year,
        source=source,
        payment_type=payment_type,
        reference=reference,
        notes=notes,
        idempotency_key=idempotency_key,
        created_by=created_by,
    )

    # --- Immutable Transaction (net / VAT / gross stored at write time) ---
    Transaction.objects.create(
        transaction_id=_generate_transaction_id(),
        tenant=tenant,
        payment=payment,
        unit_classification=tax_result.classification,
        base_amount=tax_result.base_amount,   # net income
        tax_amount=tax_result.tax_amount,     # 16% VAT (0 for residential)
        total_amount=tax_result.total_amount,  # gross received (== payment.amount)
        payment_mode=_source_to_payment_mode(source),
        reference_code=reference,  # stored exactly as received
    )

    _update_arrears(tenant, period_month, period_year)
    return payment


@transaction.atomic
def allocate_payment_fifo(
    *,
    tenant,
    amount: Decimal,
    payment_date,
    source: str = "cash",
    reference: str = "",
    notes: str = "",
    idempotency_key: str = "",
    created_by=None,
) -> list[Payment]:
    """
    Apply an incoming credit to the tenant's outstanding balances oldest-first.

    Arrears-first rule: the money clears the oldest unpaid period before newer
    ones. One Payment (+Transaction) is created per period the money touches —
    so each period's arrears clear correctly — and any remainder after all known
    arrears is booked to the current period (an overpayment / credit).

    `payment_date` is the date the money was received (the bank's posting date)
    and is the same on every chunk; only the period each chunk *clears* differs.

    Returns the Payment records created, oldest period first. If the tenant has
    no outstanding arrears, this behaves exactly like a single process_payment
    against the current period.

    NB: chunks are sized against Arrears.balance (snapshotted when the queryset
    is read), and per-chunk tax handling is whatever process_payment applies.

    Idempotency
    -----------
    Pass ``idempotency_key`` (the bank's transaction id) to make replaying the
    same credit a no-op. One credit becomes several Payment rows, so the key
    can't be used verbatim; each chunk gets ``<key>#<n>``, guarded by the
    partial unique constraint on Payment.idempotency_key. Before allocating we
    look for any chunk already carrying this prefix and, if found, return the
    existing rows untouched rather than re-splitting the money.

    The chunk ordinal — not the period — is the discriminator on purpose: FIFO
    legitimately books two chunks to the SAME period when a partial arrear is
    cleared and the remainder spills into the current month, and a period-keyed
    scheme would silently swallow the second one.

    Callers that leave the key blank keep the previous behaviour (no
    de-duplication), so manual back-office entry of a genuine second payment
    with the same reference is still possible.
    """
    remaining = Decimal(str(amount))
    created: list[Payment] = []

    # Cap so `<key>#<n>` always fits Payment.idempotency_key (max_length=100).
    base_key = (idempotency_key or "").strip()[:90]
    if base_key:
        already = list(
            Payment.objects.filter(
                tenant=tenant, idempotency_key__startswith=f"{base_key}#"
            ).order_by("id")
        )
        if already:
            return already

    # select_for_update locks the outstanding arrears rows for the life of this
    # atomic block, so two credits arriving for the same tenant concurrently are
    # serialised: the second waits, then re-reads the balances the first left
    # behind instead of allocating against stale (already-cleared) rows.
    outstanding = list(
        Arrears.objects.select_for_update()
        .filter(tenant=tenant, balance__gt=0)
        .order_by("period_year", "period_month")
    )
    for ar in outstanding:
        if remaining <= 0:
            break
        chunk = min(remaining, ar.balance)
        created.append(
            process_payment(
                tenant=tenant, amount=chunk, payment_date=payment_date,
                period_month=ar.period_month, period_year=ar.period_year,
                source=source, reference=reference, notes=notes,
                idempotency_key=f"{base_key}#{len(created)}" if base_key else "",
                created_by=created_by,
            )
        )
        remaining -= chunk

    if remaining > 0:
        # Leftover beyond known arrears applies to the period the payment is for,
        # i.e. the posting-date month (NOT the server clock — see review C2).
        created.append(
            process_payment(
                tenant=tenant, amount=remaining, payment_date=payment_date,
                period_month=payment_date.month, period_year=payment_date.year,
                source=source, reference=reference, notes=notes,
                idempotency_key=f"{base_key}#{len(created)}" if base_key else "",
                created_by=created_by,
            )
        )
    return created


def _update_arrears(tenant, period_month: int, period_year: int) -> Arrears:
    """
    Create or update the arrears record for this tenant+period,
    then recalculate the unit status.

    The obligation is ``expected_rent + expected_vat``. For a commercial unit
    `Tenant.monthly_rent` is the VAT-EXCLUSIVE base while cash received is
    VAT-inclusive, so measuring gross cash against base rent cleared the period
    16% early and left the VAT looking like an overpayment.

    Only non-void RENT payments settle it — a security deposit is a refundable
    liability and a late fee is separate income; neither discharges rent.

    The obligation itself is set when the period is RAISED — by
    ``generate_monthly_arrears`` for an ordinary month, or by the opening-balance
    import for the cutover period — and is never rewritten here. Recomputing it
    from ``tenant.monthly_rent`` on every payment silently restated the debt: an
    opening-balance row carries the brought-forward balance, not a month's rent,
    so the first payment a tenant made against it inflated a KES 1,000 opening
    arrear to a full month's KES 7,000 (and, the other way, collapsed a KES
    74,700 one). See ``repair_opening_arrears`` for the cleanup.
    """
    total_paid = rent_payments_for(tenant, period_month, period_year).aggregate(
        total=models.Sum("amount")
    )["total"] or ZERO

    # Preserve any prior waiver and carried-forward credit: both permanently
    # offset the obligation, so they must survive a recompute. Without this, a
    # payment recorded after a waiver would recompute balance from cash alone
    # and silently reverse the waiver.
    existing = (
        Arrears.objects.filter(
            tenant=tenant,
            period_month=period_month,
            period_year=period_year,
        )
        .values("waived_amount", "waive_notes", "credit_applied",
                "expected_rent", "expected_vat")
        .first()
    )
    if existing is None:
        # No row yet: money arrived for a period no billing run ever raised
        # (back-dated capture, or a tenant paying ahead). The tenant's current
        # rent is the only obligation we can infer.
        expected_rent = tenant.monthly_rent
        expected_vat = expected_vat_for(tenant, expected_rent)
        existing = {}
    else:
        expected_rent = existing["expected_rent"]
        expected_vat = existing["expected_vat"] or ZERO

    obligation = expected_rent + expected_vat
    waived_amount = existing.get("waived_amount") or ZERO
    waive_notes = existing.get("waive_notes") or ""
    credit_applied = existing.get("credit_applied") or ZERO

    covered = total_paid + waived_amount + credit_applied
    balance = max(obligation - covered, ZERO)
    is_cleared = covered >= obligation

    arrears, _ = Arrears.objects.update_or_create(
        tenant=tenant,
        period_month=period_month,
        period_year=period_year,
        defaults={
            "expected_rent": expected_rent,
            "expected_vat": expected_vat,
            "amount_paid": total_paid,
            "balance": balance,
            "is_cleared": is_cleared,
            "waived_amount": waived_amount,
            "waive_notes": waive_notes,
            "credit_applied": credit_applied,
        },
    )

    # Recalculate unit status based on current period payment.
    now = timezone.now()
    if period_month == now.month and period_year == now.year:
        recalculate_unit_status(tenant.unit, covered, obligation=obligation)

    return arrears


def available_credit(tenant) -> Decimal:
    """Overpayment a tenant has banked but not yet had applied to a period.

    Credit = everything paid/waived beyond each period's obligation, less the
    credit already carried into other periods. Previously this figure had
    nowhere to live: `balance` was floored at zero, so a tenant who prepaid
    three months was billed in full — and dunned — the following month.
    """
    surplus = ZERO
    consumed = ZERO
    for row in Arrears.objects.filter(tenant=tenant).only(
        "expected_rent", "expected_vat", "amount_paid", "waived_amount", "credit_applied"
    ):
        surplus += max(row.covered - row.expected_total, ZERO)
        consumed += row.credit_applied or ZERO
    return max(surplus - consumed, ZERO)


def apply_available_credit(arrears: Arrears) -> Arrears:
    """Draw down any banked credit against an open arrears row.

    Called when a new period is raised so a prepayment actually pays for the
    month it was meant for.
    """
    if arrears.balance <= 0:
        return arrears
    credit = min(available_credit(arrears.tenant), arrears.balance)
    if credit <= 0:
        return arrears

    arrears.credit_applied = (arrears.credit_applied or ZERO) + credit
    arrears.balance = max(arrears.expected_total - arrears.covered, ZERO)
    arrears.is_cleared = arrears.covered >= arrears.expected_total
    arrears.save(update_fields=["credit_applied", "balance", "is_cleared", "updated_at"])
    return arrears


class CreditAlreadyResolved(Exception):
    """The IPN credit is no longer awaiting reconciliation."""


@transaction.atomic
def assign_unmatched_credit(*, event_id: int, tenant, actor=None):
    """Book an UNMATCHED bank credit against a chosen tenant.

    Single implementation shared by the API viewset, the admin action and any
    management command. It used to exist twice with *different* safety
    properties — the admin copy neither locked the row nor re-checked status, so
    two admins reconciling the same credit could book it twice, and neither copy
    passed an idempotency key to the allocator.

    Returns (event, payments). Raises CreditAlreadyResolved if another operator
    got there first.
    """
    from apps.accounts import audit

    from .coop_ipn import _parse_narration, _posting_date
    from .models import CoopIpnEvent, CoopIpnStatus

    # Lock + re-check under the lock so two clicks can't double-book.
    event = CoopIpnEvent.objects.select_for_update().get(pk=event_id)
    if event.status != CoopIpnStatus.UNMATCHED:
        raise CreditAlreadyResolved(
            f"Event is not unmatched (status: {event.get_status_display()})."
        )

    pay_date = _posting_date(event.raw_payload or {})
    channel = _parse_narration(event.narration).get("channel", event.channel or "bank")
    payments = allocate_payment_fifo(
        tenant=tenant,
        amount=event.amount,
        payment_date=pay_date,
        source=channel,
        reference=event.transaction_id,
        notes=f"Manually assigned by {actor or 'system'}; IPN event #{event.pk}",
        # The bank's transaction id makes a re-assignment (or a racing
        # reprocess) a no-op instead of a second booking.
        idempotency_key=event.transaction_id,
        created_by=actor if getattr(actor, "is_authenticated", False) else None,
    )
    event.status = CoopIpnStatus.RECORDED
    event.detail = f"Manually assigned to {tenant} by {actor or 'system'}"
    event.payment = payments[0]
    event.save(update_fields=["status", "detail", "payment"])

    audit.record(
        actor=actor,
        action="credit.assign",
        object_type="coop_ipn_event",
        object_id=event.pk,
        summary=f"Assigned KES {event.amount} ({event.transaction_id}) to {tenant}",
        old_values={"status": CoopIpnStatus.UNMATCHED},
        new_values={"status": CoopIpnStatus.RECORDED, "tenant_id": tenant.pk},
    )
    return event, payments


@transaction.atomic
def void_payment(payment: Payment, *, actor=None, reason: str = "") -> Payment:
    """Unwind a payment without mutating or deleting it.

    Payments are immutable financial records, so a void marks the row rather
    than editing it, posts a mirror-image REVERSAL journal entry, and
    re-derives the affected period's arrears. The original NORMAL entry is left
    intact for audit.

    This replaces the previous approach of inserting an equal-and-opposite
    Payment with a NEGATIVE amount, which:
      * never reached the ledger for commercial tenants at all — posting routes
        through `split_tax_inclusive`, which rejects a non-positive amount, so
        the reversal died as a PostingFailure and the GL kept showing income;
      * dropped `payment_type`, so voiding a deposit posted against rental
        income (4110) instead of the deposit accounts (1030/2100).

    Idempotent: voiding an already-void payment is a no-op.
    """
    from apps.accounts import audit

    if payment.voided_at:
        return payment

    payment.voided_at = timezone.now()
    payment.voided_by = actor if getattr(actor, "is_authenticated", False) else None
    payment.void_reason = (reason or "")[:255]
    payment.save(update_fields=["voided_at", "voided_by", "void_reason"])

    # Post the mirror-image entry. The post_save signal deliberately skips
    # voided rows so the original entry is preserved, so we post it here.
    from apps.ledger.signals import _safe_post

    def _post_reversal():
        from apps.ledger.posting import reverse_payment
        reverse_payment(payment)

    _safe_post(
        source_type="payment", source_id=payment.pk, kind="reversal",
        operation="reverse", fn=_post_reversal,
    )

    _update_arrears(payment.tenant, payment.period_month, payment.period_year)

    audit.record(
        actor=actor,
        action="payment.void",
        object_type="payment",
        object_id=payment.pk,
        summary=f"Voided KES {payment.amount} for {payment.tenant} — {reason or 'no reason given'}",
        old_values={"voided_at": None, "amount": payment.amount},
        new_values={"voided_at": payment.voided_at, "void_reason": payment.void_reason},
    )
    return payment


def get_collection_progress(period_month: int, period_year: int) -> dict:
    """
    Return collection progress for a given month:
    {expected, collected, percentage}

    Both sides are measured on the same basis: expected is the full obligation
    (rent plus VAT where it applies) and collected counts only non-void rent.
    Previously `expected` was base rent while `collected` swept in deposits and
    late fees, so the percentage reconciled with neither the P&L nor arrears.
    """
    from apps.tenants.models import Tenant, TenantStatus

    active_tenants = Tenant.objects.filter(status=TenantStatus.ACTIVE).select_related("unit")
    expected = sum(
        (t.monthly_rent + expected_vat_for(t, t.monthly_rent) for t in active_tenants),
        ZERO,
    )

    collected = Payment.objects.filter(
        period_month=period_month,
        period_year=period_year,
        payment_type__in=SETTLES_RENT,
        voided_at__isnull=True,
    ).aggregate(total=models.Sum("amount"))["total"] or ZERO

    percentage = (collected / expected * 100) if expected else ZERO

    return {
        "expected": expected,
        "collected": collected,
        "percentage": round(percentage, 1),
        "period_month": period_month,
        "period_year": period_year,
    }
