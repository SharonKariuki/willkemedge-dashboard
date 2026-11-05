from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0013_tenant_first_rent_month"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenant",
            name="vat_exempt",
            field=models.BooleanField(
                default=False, help_text="Tick for a commercial letting that is not charged VAT."
            ),
        ),
    ]
