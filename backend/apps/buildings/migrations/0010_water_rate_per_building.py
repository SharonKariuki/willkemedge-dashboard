from decimal import Decimal

from django.db import migrations, models

# The tariff is not portfolio-wide. Dr Osoro confirmed (Sept 2026) that it is
# set per property:
#
#   Donholm Nairobi            KES 150 / unit
#   Matasia Commercial         KES 200 / unit
#   Matasia Residential        KES 200 / unit
#
# Migration 0009 moved *every* building still on 150 up to 200, which swept
# Donholm up with the rest. This puts Donholm back and pins the two Matasia
# buildings explicitly so the figure is stated rather than inherited from the
# field default.
RATES = {
    "DON": Decimal("150.00"),
    "MC": Decimal("200.00"),
    "MAC": Decimal("200.00"),
    "MAT": Decimal("200.00"),
    "MAR": Decimal("200.00"),
}

# Matched only when the short code is missing or spelled differently — the code
# is the reliable key, this is the safety net for a building loaded before the
# coding scheme landed.
NAME_RATES = (
    ("Donholm", Decimal("150.00")),
    ("Matasia", Decimal("200.00")),
)


def set_rates(apps, schema_editor):
    Building = apps.get_model("buildings", "Building")

    matched = set()
    for code, rate in RATES.items():
        qs = Building.objects.filter(code__iexact=code)
        matched.update(qs.values_list("pk", flat=True))
        qs.update(water_rate_per_unit=rate)

    for fragment, rate in NAME_RATES:
        Building.objects.filter(name__icontains=fragment).exclude(pk__in=matched).update(
            water_rate_per_unit=rate
        )


def unset_rates(apps, schema_editor):
    """No-op.

    0009 flattened the per-building rates, so there is no earlier state worth
    restoring — reversing this would only re-introduce the bug it fixes.
    Historic UtilityCharge rows are untouched either way: each one reports the
    rate it was actually billed at, derived from its own amount and units.
    """


class Migration(migrations.Migration):

    dependencies = [
        ("buildings", "0009_water_rate_200"),
    ]

    operations = [
        migrations.AlterField(
            model_name="building",
            name="water_rate_per_unit",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("200.00"),
                help_text=(
                    "Tariff charged per unit of water consumed (KES). Set per "
                    "property: Donholm bills at 150/unit, Matasia commercial and "
                    "residential at 200/unit."
                ),
                max_digits=8,
            ),
        ),
        migrations.RunPython(set_rates, unset_rates),
    ]
