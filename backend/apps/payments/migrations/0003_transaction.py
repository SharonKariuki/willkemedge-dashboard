"""
Migration: add Transaction model to payments app.

Depends on: payments 0002_tenantnotification, buildings 0002_unit_classification
"""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("payments", "0002_tenantnotification"),
        ("buildings", "0002_unit_classification"),
        ("tenants", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Transaction",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                (
                    "transaction_id",
                    models.CharField(
                        editable=False,
                        help_text="System-generated unique transaction identifier (TXN-<uuid4_hex[:16]>).",
                        max_length=40,
                        unique=True,
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="transactions",
                        to="tenants.tenant",
                    ),
                ),
                (
                    "payment",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="transaction",
                        to="payments.payment",
                        help_text="The underlying Payment record this transaction corresponds to.",
                    ),
                ),
                (
                    "unit_classification",
                    models.CharField(
                        choices=[("RESIDENTIAL", "Residential"), ("BUSINESS", "Business / Commercial")],
                        help_text="Snapshotted from unit.classification at transaction creation time.",
                        max_length=15,
                    ),
                ),
                (
                    "base_amount",
                    models.DecimalField(
                        decimal_places=2,
                        help_text="Rent amount before tax.",
                        max_digits=10,
                    ),
                ),
                (
                    "tax_amount",
                    models.DecimalField(
                        decimal_places=2,
                        help_text="VAT applied (0 for RESIDENTIAL, 16 % for BUSINESS).",
                        max_digits=10,
                    ),
                ),
                (
                    "total_amount",
                    models.DecimalField(
                        decimal_places=2,
                        help_text="base_amount + tax_amount. Stored at write time.",
                        max_digits=10,
                    ),
                ),
                (
                    "payment_mode",
                    models.CharField(
                        choices=[
                            ("MPESA", "M-Pesa"),
                            ("BANK", "Bank Transfer"),
                            ("CASH", "Cash"),
                            ("CHEQUE", "Cheque"),
                        ],
                        max_length=10,
                    ),
                ),
                (
                    "reference_code",
                    models.CharField(
                        blank=True,
                        help_text="External reference stored exactly as received.",
                        max_length=100,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "payments_transaction",
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(fields=["transaction_id"], name="tx_id_idx"),
                    models.Index(fields=["tenant", "-created_at"], name="tx_tenant_idx"),
                    models.Index(fields=["unit_classification"], name="tx_classification_idx"),
                ],
            },
        ),
    ]
