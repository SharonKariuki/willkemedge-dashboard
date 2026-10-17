"""One current tenancy per unit, enforced by the database.

Pre-flight first, in the pattern of buildings/0013: if live data already has a
unit with two current tenants, the migration stops with the unit and tenant
ids instead of failing half-way on the constraint. build.sh runs migrate under
errexit, so the deploy aborts and Render keeps serving the previous version.
Fix the rows (move the wrong tenancy out) and redeploy.
"""
from django.conf import settings
from django.db import migrations, models
from django.db.models import Count

CURRENT = ["active", "notice_given"]


def assert_one_current_tenant_per_unit(apps, schema_editor):
    Tenant = apps.get_model("tenants", "Tenant")
    clashes = (
        Tenant.objects.filter(status__in=CURRENT, unit__isnull=False)
        .values("unit_id").annotate(n=Count("id")).filter(n__gt=1)
    )
    if not clashes:
        return
    lines = []
    for row in clashes:
        ids = list(
            Tenant.objects.filter(status__in=CURRENT, unit_id=row["unit_id"]).values_list("id", flat=True)
        )
        lines.append(f"  unit {row['unit_id']}: current tenants {ids}")
    raise RuntimeError(
        "Refusing to add tenant_one_current_per_unit: these units have more than "
        "one current tenant. Move the wrong tenancy out, then redeploy.\n" + "\n".join(lines)
    )


class Migration(migrations.Migration):

    dependencies = [
        ('buildings', '0014_unit_unit_monthly_rent_non_negative'),
        ('tenants', '0010_tenant_documents_in_database'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(assert_one_current_tenant_per_unit, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='tenant',
            constraint=models.UniqueConstraint(
                condition=models.Q(('status__in', ['active', 'notice_given'])),
                fields=('unit',),
                name='tenant_one_current_per_unit',
            ),
        ),
    ]
