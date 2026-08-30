from decimal import Decimal

from django.db import migrations, models

OLD_RATE = Decimal("150.00")
NEW_RATE = Decimal("200.00")


def raise_rate(apps, schema_editor):
    """Move every building still on the old 150/unit tariff to 200/unit.

    Buildings deliberately set to some other rate are left alone.
    """
    Building = apps.get_model("buildings", "Building")
    Building.objects.filter(water_rate_per_unit=OLD_RATE).update(water_rate_per_unit=NEW_RATE)


def lower_rate(apps, schema_editor):
    Building = apps.get_model("buildings", "Building")
    Building.objects.filter(water_rate_per_unit=NEW_RATE).update(water_rate_per_unit=OLD_RATE)


class Migration(migrations.Migration):

    dependencies = [
        ('buildings', '0008_building_property_type'),
    ]

    operations = [
        migrations.AlterField(
            model_name='building',
            name='water_rate_per_unit',
            field=models.DecimalField(decimal_places=2, default=Decimal('200.00'), help_text='Tariff charged per unit of water consumed (KES). Donholm bills at 200/unit.', max_digits=8),
        ),
        migrations.RunPython(raise_rate, lower_rate),
    ]
