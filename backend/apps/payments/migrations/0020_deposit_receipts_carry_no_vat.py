"""Security deposits carry no VAT: correct the receipts that said they did.

Every commercial receipt had 16% split out of it, deposits included, so a
KES 116,000 deposit was recorded as KES 100,000 + KES 16,000 VAT. A deposit is
refundable money held for the tenant, not a supply, and the ledger never booked
VAT on one (it posts the gross to 2100) — only the Transaction row, which the
receipt prints, was wrong. Net becomes the gross and the VAT zero.
"""
from decimal import Decimal

from django.db import migrations
from django.db.models import F


def forwards(apps, schema_editor):
    Transaction = apps.get_model("payments", "Transaction")
    Transaction.objects.filter(
        payment__payment_type="deposit", tax_amount__gt=0
    ).update(base_amount=F("total_amount"), tax_amount=Decimal("0.00"))


class Migration(migrations.Migration):

    dependencies = [
        ("payments", "0019_tenant_credits_refunds"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
