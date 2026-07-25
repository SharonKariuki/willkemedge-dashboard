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

from apps.buildings.services import recalculate_unit_status

from .models import Arrears, Payment, PaymentMode, Transaction
from .tax_service import split_tax_inclusive


def _generate_transaction_id() -> str:
    """Return a unique, traceable transaction ID: TXN-<16 hex chars>."""
    return f"TXN-{uuid.uuid4().hex[:16].upper()}"


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
    de-duplicated payment: a re-submission with the same key returns the
    already-recorded Payment instead of double-booking (and double-reducing
    arrears). The key is enforced by a partial unique constraint at the DB
    level, so concurrent retries that both pass the pre-check are still caught
    via IntegrityError. FIFO allocation intentionally leaves the key blank —
    it splits one credit into several Payment rows that share a reference — so
    it is never de-duplicated here.
    """
    if idempotency_key:
        existing = Payment.objects.filter(idempotency_key=idempotency_key).first()
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
        )
    except IntegrityError:
        # A concurrent retry won the race and inserted the row first; return it
        # rather than surfacing the constraint violation.
        if idempotency_key:
            existing = Payment.objects.filter(idempotency_key=idempotency_key).first()
            if existing:
                return existing
        raise


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
        reference=reference,
        notes=notes,
        idempotency_key=idempotency_key,
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
    """
    remaining = Decimal(str(amount))
    created: list[Payment] = []

    outstanding = list(
        Arrears.objects.filter(tenant=tenant, balance__gt=0)
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
            )
        )
    return created


def _update_arrears(tenant, period_month: int, period_year: int) -> Arrears:
    """
    Create or update the arrears record for this tenant+period,
    then recalculate the unit status.
    """
    expected_rent = tenant.monthly_rent

    total_paid = Payment.objects.filter(
        tenant=tenant,
        period_month=period_month,
        period_year=period_year,
    ).aggregate(total=models.Sum("amount"))["total"] or Decimal("0")

    # Preserve any prior waiver: a waived amount permanently offsets the
    # obligation, so it must be folded into the balance/cleared computation.
    # Without this, a payment recorded after a waiver would recompute
    # balance = expected_rent - total_paid and silently reverse the waiver.
    existing = (
        Arrears.objects.filter(
            tenant=tenant,
            period_month=period_month,
            period_year=period_year,
        )
        .values("waived_amount", "waive_notes")
        .first()
    )
    waived_amount = (existing or {}).get("waived_amount") or Decimal("0")
    waive_notes = (existing or {}).get("waive_notes") or ""

    covered = total_paid + waived_amount
    balance = max(expected_rent - covered, Decimal("0"))
    is_cleared = covered >= expected_rent

    arrears, _ = Arrears.objects.update_or_create(
        tenant=tenant,
        period_month=period_month,
        period_year=period_year,
        defaults={
            "expected_rent": expected_rent,
            "amount_paid": total_paid,
            "balance": balance,
            "is_cleared": is_cleared,
            "waived_amount": waived_amount,
            "waive_notes": waive_notes,
        },
    )

    # Recalculate unit status based on current period payment.
    now = timezone.now()
    if period_month == now.month and period_year == now.year:
        recalculate_unit_status(tenant.unit, total_paid)

    return arrears


def get_collection_progress(period_month: int, period_year: int) -> dict:
    """
    Return collection progress for a given month:
    {expected, collected, percentage}
    """
    from apps.tenants.models import Tenant, TenantStatus

    active_tenants = Tenant.objects.filter(status=TenantStatus.ACTIVE)
    expected = sum(t.monthly_rent for t in active_tenants)

    collected = Payment.objects.filter(
        period_month=period_month,
        period_year=period_year,
    ).aggregate(total=models.Sum("amount"))["total"] or Decimal("0")

    percentage = (collected / expected * 100) if expected else Decimal("0")

    return {
        "expected": expected,
        "collected": collected,
        "percentage": round(percentage, 1),
        "period_month": period_month,
        "period_year": period_year,
    }
