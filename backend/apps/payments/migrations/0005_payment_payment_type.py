"""Add payment_type to Payment so income can be split rent vs late-fee vs deposit."""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("payments", "0004_rename_tx_id_idx_payments_tr_transac_e96a4f_idx_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="payment",
            name="payment_type",
            field=models.CharField(
                choices=[
                    ("rent", "Rental Income (4000)"),
                    ("late_fee", "Late Fees (4010)"),
                    ("deposit", "Security Deposit (2100)"),
                    ("other", "Other Income"),
                ],
                default="rent",
                help_text="Used to split income into 4000 (rent), 4010 (late fees), or 2100 (deposit liability).",
                max_length=10,
            ),
        ),
    ]
