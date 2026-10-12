"""Pre-flight for the database-level financial invariants.

This is the HEAD of the constraint chain: `buildings/0014`, `expenses/0012`,
`payments/0021` and `tenants/0009` all depend on it, so it runs before
any CHECK or UNIQUE constraint is installed anywhere.

It changes nothing. It scans live data against every rule those migrations are
about to enforce and, if anything is broken, raises with the offending row ids
so the deploy stops BEFORE the schema is touched.

Why refuse rather than repair
-----------------------------
`0018_arrears_check_constraints` established a "heal, then constrain" pattern
for an arrears balance that was safe to clamp at zero. These rules are not like
that: each one guards an AMOUNT or a PERIOD on a financial record, and silently
rewriting either is restating the books. A migration must never do that
unattended. The operator gets the list, decides, corrects the rows deliberately,
and redeploys.

Failing here is safe. `build.sh` runs under `set -o errexit`, so the release
aborts and Render keeps serving the previous deploy â€” nothing goes down and no
schema change is half-applied.

Run `python manage.py check_db_invariants` against production first to find out
whether this will pass, before you deploy.
"""
from django.db import migrations

from config.db_invariants import duplicate_utility_charges, format_report, violations


def assert_invariants_hold(apps, schema_editor):
    broken = violations(apps)
    dupes = duplicate_utility_charges(apps)
    if not broken and not dupes:
        return
    raise RuntimeError(
        "Refusing to install the financial CHECK constraints: live data breaks "
        "rules they would enforce.\n\n"
        + format_report(broken, dupes)
        + "\n\nNothing has been changed and no constraint was added. Correct these "
        "rows deliberately (a void, a corrected charge, a recorded data fix), "
        "confirm with `manage.py check_db_invariants`, then redeploy."
    )


def noop(apps, schema_editor):
    """Nothing to undo â€” the pre-flight only reads."""


class Migration(migrations.Migration):

    # Depends on the current head of every app it inspects, so all four models
    # are present in the historical registry `RunPython` is handed. Without
    # these the pre-flight raises KeyError('payments') instead of checking
    # anything. None of these creates a cycle: each is an EARLIER migration than
    # the constraint migrations that depend on this one.
    dependencies = [
        ("buildings", "0012_building_photo"),
        ("payments", "0020_deposit_receipts_carry_no_vat"),
        ("expenses", "0011_backfill_maintenance_expense_unit"),
        ("tenants", "0008_tenant_id_unique_while_current"),
    ]

    operations = [
        migrations.RunPython(assert_invariants_hold, noop),
    ]
