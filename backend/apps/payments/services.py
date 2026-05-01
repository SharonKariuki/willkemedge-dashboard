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

from django.db import models, transaction
from django.utils import timezone

from apps.buildings.services import recalculate_unit_status

from .models import Arrears, Payment, PaymentMode, Transaction
from .tax_service import calculate_tax


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


@transaction.atomic
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
    """
    unit = tenant.unit
    classification = unit.classification  # the trigger field

    # --- Tax calculation (centralised) ---
    tax_result = calculate_tax(Decimal(str(amount)), classification)

    # --- Immutable Payment (base amount kept for backwards-compat) ---
    payment = Payment.objects.create(
        tenant=tenant,
        amount=tax_result.base_amount,
        payment_date=payment_date,
        period_month=period_month,
        period_year=period_year,
        source=source,
        reference=reference,
        notes=notes,
    )

    # --- Immutable Transaction (all fields stored at write time) ---
    Transaction.objects.create(
        transaction_id=_generate_transaction_id(),
        tenant=tenant,
        payment=payment,
        unit_classification=tax_result.classification,
        base_amount=tax_result.base_amount,
        tax_amount=tax_result.tax_amount,
        total_amount=tax_result.total_amount,
        payment_mode=_source_to_payment_mode(source),
        reference_code=reference,  # stored exactly as received
    )

    _update_arrears(tenant, period_month, period_year)
    return payment


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

    balance = max(expected_rent - total_paid, Decimal("0"))
    is_cleared = total_paid >= expected_rent

    arrears, _ = Arrears.objects.update_or_create(
        tenant=tenant,
        period_month=period_month,
        period_year=period_year,
        defaults={
            "expected_rent": expected_rent,
            "amount_paid": total_paid,
            "balance": balance,
            "is_cleared": is_cleared,
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
