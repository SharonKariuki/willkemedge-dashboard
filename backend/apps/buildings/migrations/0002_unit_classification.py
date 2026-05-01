"""
Migration: add UnitClassification field to Unit.

Depends on: buildings 0001_initial
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("buildings", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="unit",
            name="classification",
            field=models.CharField(
                choices=[("RESIDENTIAL", "Residential"), ("BUSINESS", "Business / Commercial")],
                default="RESIDENTIAL",
                db_index=True,
                help_text=(
                    "RESIDENTIAL = 0 % VAT. "
                    "BUSINESS = 16 % VAT applied to base rent at payment time."
                ),
                max_length=15,
            ),
        ),
    ]
