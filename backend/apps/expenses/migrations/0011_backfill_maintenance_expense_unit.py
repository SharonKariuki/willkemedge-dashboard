"""Backfill the unit on expenses that a maintenance request created.

A maintenance request is always raised against one unit, and until now the
expense it generated recorded only the building. Those rows already carry the
unit — through MaintenanceRequest.expense — so the link can be restored rather
than left blank for every cost booked before this release.

Only rows still missing a unit are touched, and the building is left alone: it
was already set from the same unit, so the two cannot disagree.
"""
from django.db import migrations


def backfill_unit(apps, schema_editor):
    MaintenanceRequest = apps.get_model("buildings", "MaintenanceRequest")
    Expense = apps.get_model("expenses", "Expense")

    linked = dict(
        MaintenanceRequest.objects.exclude(expense__isnull=True).values_list(
            "expense_id", "unit_id"
        )
    )
    if not linked:
        return

    # Skip any expense that already names a unit — a hand-set link wins.
    unset_ids = Expense.objects.filter(
        pk__in=linked.keys(), unit__isnull=True
    ).values_list("pk", flat=True)

    rows = [Expense(pk=pk, unit_id=linked[pk]) for pk in unset_ids]
    if rows:
        Expense.objects.bulk_update(rows, ["unit"], batch_size=500)


class Migration(migrations.Migration):

    dependencies = [
        ("buildings", "0009_water_rate_200"),
        ("expenses", "0010_expense_unit"),
    ]

    operations = [
        # Irreversible by design: clearing the unit again would also wipe any
        # unit a user set by hand after this ran.
        migrations.RunPython(backfill_unit, migrations.RunPython.noop),
    ]
