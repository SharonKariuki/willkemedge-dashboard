"""Add the Arrears integrity constraints — after the data is known to satisfy them.

These two checks were originally in 0015, alongside the fields they guard. That
ordering failed on production: a legacy row (expected_rent 0.00, balance
-1000.00, created by an early seed) violated `balance >= 0`, so the whole
migration rolled back and the deploy died.

A constraint cannot be introduced before the migration that establishes the
invariant it asserts. 0016 recomputes every arrears row and clamps the balance at
zero, so by the time this migration runs the data is coherent — including rows
that were incoherent before this release.

The defensive clamp below covers the case where a row was inserted between 0016
and this migration (a concurrent write during a long deploy), so the constraint
never fails on a technicality.
"""
from django.db import migrations, models


def clamp_negative_balances(apps, schema_editor):
    """Floor any remaining negative balance at zero before the check is applied."""
    Arrears = apps.get_model("payments", "Arrears")
    fixed = Arrears.objects.filter(balance__lt=0).update(balance=0)
    if fixed:
        print(f"\n  Clamped {fixed} negative arrears balance(s) to 0.")  # noqa: T201


def noop(apps, schema_editor):
    """Nothing to undo — the clamp is not reversible and need not be."""


class Migration(migrations.Migration):

    dependencies = [
        ("payments", "0017_convert_legacy_void_payments"),
    ]

    operations = [
        migrations.RunPython(clamp_negative_balances, noop),
        migrations.AddConstraint(
            model_name="arrears",
            constraint=models.CheckConstraint(
                condition=models.Q(("balance__gte", 0)),
                name="arrears_balance_non_negative",
            ),
        ),
        migrations.AddConstraint(
            model_name="arrears",
            constraint=models.CheckConstraint(
                condition=models.Q(("period_month__gte", 1), ("period_month__lte", 12)),
                name="arrears_period_month_valid",
            ),
        ),
    ]
