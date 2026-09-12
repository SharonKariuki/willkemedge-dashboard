"""Rent is payable on or before the 5th, for every letting.

``due_day`` is a per-tenant override of a portfolio-wide policy, and it had
drifted: the seeds and the reconciliation commands all write 5, but the field
is editable from the tenant form and nothing held it there. Every message a
tenant receives keys off it — the reminder SMS N days before, the overdue SMS
on and after, and the due date printed on the statement — so a tenant sitting
on some other day is told a different deadline from the one the landlord
enforces, on all three channels at once.

The landlord's instruction is one date for the whole roster, commercial
included: rent for a month is due by the 5th of that month. This pins the
stored data to it.

Not reversible in any useful sense — the overrides being retired were drift, not
agreements, and there is nothing worth restoring them to. The reverse is a
no-op so a rollback of the code does not fail on this migration.
"""
from django.db import migrations, models
import django.core.validators


RENT_DUE_DAY = 5


def pin_due_day(apps, schema_editor):
    Tenant = apps.get_model("tenants", "Tenant")
    Tenant.objects.exclude(due_day=RENT_DUE_DAY).update(due_day=RENT_DUE_DAY)


def noop(apps, schema_editor):
    """See the module docstring: there is nothing to restore."""


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0005_tenant_agreed_deposit"),
    ]

    operations = [
        migrations.AlterField(
            model_name="tenant",
            name="due_day",
            field=models.PositiveSmallIntegerField(
                default=5,
                validators=[
                    django.core.validators.MinValueValidator(1),
                    django.core.validators.MaxValueValidator(31),
                ],
                help_text=(
                    "Day of the month rent is due, in the month being billed. "
                    "Portfolio policy is the 5th and every tenant is on it — "
                    "change this only for a letting genuinely agreed otherwise."
                ),
            ),
        ),
        migrations.RunPython(pin_due_day, noop),
    ]
