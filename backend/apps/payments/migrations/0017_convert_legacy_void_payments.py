"""Convert legacy negative "VOID:" payments to the new void model.

Before this release, authorising a bank reversal inserted an equal-and-opposite
Payment with a NEGATIVE amount and `reference="VOID:<original>"`. That approach
left two problems in any database where it was used:

  * For a commercial tenant the compensating row never reached the ledger at
    all — posting routes through `split_tax_inclusive`, which rejects a
    non-positive amount, so the entry died as a PostingFailure and the GL kept
    showing the original income.
  * The row carried no `payment_type`, so a voided deposit posted against
    rental income instead of the deposit accounts.

Voids are now a flag on the original row plus a mirror-image journal entry.
This migration migrates the old shape onto the new one: the original payment is
marked void and the negative row is removed.

Ledger entries are deliberately NOT rewritten here — a migration should not
silently restate the books. Run ``python manage.py retry_posting_failures``
afterwards to post the reversal entries that previously failed, then review any
still-open PostingFailure rows.

Safe to run on a database that never used the old flow: it simply finds nothing.
"""
from django.db import migrations


def convert(apps, schema_editor):
    Payment = apps.get_model("payments", "Payment")

    legacy = Payment.objects.filter(amount__lt=0, reference__startswith="VOID:")
    converted = 0

    for neg in legacy.iterator(chunk_size=200):
        original_ref = neg.reference[len("VOID:"):]

        # The old code wrote the original's reference, or its pk when the
        # reference was blank. Match on the strongest signal available.
        candidates = Payment.objects.filter(
            tenant_id=neg.tenant_id,
            amount=-neg.amount,
            period_month=neg.period_month,
            period_year=neg.period_year,
            voided_at__isnull=True,
        )
        original = candidates.filter(reference=original_ref).first()
        if original is None and original_ref.isdigit():
            original = candidates.filter(pk=int(original_ref)).first()
        if original is None:
            original = candidates.first()

        if original is not None:
            original.voided_at = neg.created_at
            original.void_reason = (
                neg.notes or "Reversal authorized (migrated from legacy void entry)"
            )[:255]
            original.save(update_fields=["voided_at", "void_reason"])
            converted += 1

        neg.delete()

    if converted:
        # 0016 recomputed arrears while the negative rows were still present and
        # counting toward `amount_paid`. Removing them changes those sums, so the
        # recompute has to run again on the settled data.
        import importlib

        recompute = importlib.import_module(
            "apps.payments.migrations.0016_recompute_arrears_with_vat"
        ).recompute
        recompute(apps, schema_editor)

        print(  # noqa: T201 — migration progress belongs on stdout
            f"\n  Converted {converted} legacy void payment(s) to the void flag "
            f"and recomputed arrears. Run `manage.py retry_posting_failures` to "
            f"post their reversal entries."
        )


def unconvert(apps, schema_editor):
    """Restore the negative-payment shape for a rollback."""
    Payment = apps.get_model("payments", "Payment")

    for original in Payment.objects.filter(voided_at__isnull=False).iterator(chunk_size=200):
        Payment.objects.create(
            tenant_id=original.tenant_id,
            amount=-original.amount,
            payment_date=original.payment_date,
            period_month=original.period_month,
            period_year=original.period_year,
            source=original.source,
            reference=f"VOID:{original.reference or original.pk}",
            notes=original.void_reason,
        )
        original.voided_at = None
        original.void_reason = ""
        original.save(update_fields=["voided_at", "void_reason"])


class Migration(migrations.Migration):

    dependencies = [
        ("payments", "0016_recompute_arrears_with_vat"),
    ]

    operations = [
        migrations.RunPython(convert, unconvert),
    ]
