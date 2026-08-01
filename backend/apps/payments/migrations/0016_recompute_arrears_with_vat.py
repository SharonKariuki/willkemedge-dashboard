"""Recompute every arrears row on the corrected basis.

Two defects are being repaired in the stored data, not just in the code:

1. **Commercial VAT.** `expected_rent` holds the VAT-EXCLUSIVE base rent, while
   `Payment.amount` holds VAT-INCLUSIVE cash. Comparing them directly cleared a
   commercial tenant's period as soon as they had paid the base rent, treating
   the 16% owed to KRA as an overpayment. `expected_vat` is populated here and
   the balance re-derived against rent + VAT.

2. **Non-rent payments settling rent.** `amount_paid` summed every payment type,
   so a security deposit (a refundable liability) or a late fee marked the rent
   paid. It is recomputed here from RENT payments only.

Reversible: the backwards pass restores the previous (incorrect) basis so the
migration can be rolled back cleanly alongside a code rollback.
"""
from decimal import ROUND_HALF_UP, Decimal

from django.db import migrations
from django.db.models import Sum

VAT_RATE = Decimal("0.16")
ZERO = Decimal("0")


def _vat_for(unit, base_rent):
    """16% on top of base rent for a BUSINESS unit; nothing for residential."""
    base = Decimal(str(base_rent or 0))
    if base <= 0 or unit is None or unit.classification != "BUSINESS":
        return ZERO
    return (base * VAT_RATE).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def recompute(apps, schema_editor):
    Arrears = apps.get_model("payments", "Arrears")
    Payment = apps.get_model("payments", "Payment")

    rows = Arrears.objects.select_related("tenant", "tenant__unit").all()
    for ar in rows.iterator(chunk_size=500):
        unit = getattr(ar.tenant, "unit", None)
        expected_vat = _vat_for(unit, ar.expected_rent)

        # Rent only, and only rows that are not void.
        paid = Payment.objects.filter(
            tenant_id=ar.tenant_id,
            period_month=ar.period_month,
            period_year=ar.period_year,
            payment_type="rent",
            voided_at__isnull=True,
        ).aggregate(total=Sum("amount"))["total"] or ZERO

        obligation = (ar.expected_rent or ZERO) + expected_vat
        covered = paid + (ar.waived_amount or ZERO) + (ar.credit_applied or ZERO)

        ar.expected_vat = expected_vat
        ar.amount_paid = paid
        ar.balance = max(obligation - covered, ZERO)
        ar.is_cleared = covered >= obligation
        ar.save(update_fields=["expected_vat", "amount_paid", "balance", "is_cleared"])


def restore_previous_basis(apps, schema_editor):
    Arrears = apps.get_model("payments", "Arrears")
    Payment = apps.get_model("payments", "Payment")

    for ar in Arrears.objects.all().iterator(chunk_size=500):
        paid = Payment.objects.filter(
            tenant_id=ar.tenant_id,
            period_month=ar.period_month,
            period_year=ar.period_year,
        ).aggregate(total=Sum("amount"))["total"] or ZERO
        covered = paid + (ar.waived_amount or ZERO)
        ar.expected_vat = ZERO
        ar.amount_paid = paid
        ar.balance = max((ar.expected_rent or ZERO) - covered, ZERO)
        ar.is_cleared = covered >= (ar.expected_rent or ZERO)
        ar.save(update_fields=["expected_vat", "amount_paid", "balance", "is_cleared"])


class Migration(migrations.Migration):

    dependencies = [
        ("payments", "0015_remove_payment_unique_payment_idempotency_key_and_more"),
    ]

    operations = [
        migrations.RunPython(recompute, restore_previous_basis),
    ]
