"""Give existing accounts a role.

`User.role` defaults to VIEWER so a newly created account cannot move money
until it is deliberately promoted. That default must not be applied to accounts
that already exist: before roles were introduced every authenticated user had
full access, and silently demoting them on deploy would lock the owner out of
their own dashboard.

Existing users are therefore promoted to OWNER, which preserves exactly the
access they had the moment before this migration ran. Tightening from there is a
deliberate admin action, not a side effect of a deploy.
"""
from django.db import migrations


def promote_existing_users(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    User.objects.update(role="owner")


def demote_all(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    User.objects.update(role="viewer")


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0004_user_role_financialauditlog"),
    ]

    operations = [
        migrations.RunPython(promote_existing_users, demote_all),
    ]
