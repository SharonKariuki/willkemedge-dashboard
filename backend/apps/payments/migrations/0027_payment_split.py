from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("payments", "0026_deposit_settlement"),
    ]

    operations = [
        migrations.AddField(
            model_name="payment",
            name="split_group",
            field=models.CharField(blank=True, db_index=True, default="", max_length=32),
        ),
        migrations.AddField(
            model_name="payment",
            name="split_index",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="payment",
            name="split_count",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="payment",
            name="split_total",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True),
        ),
    ]
