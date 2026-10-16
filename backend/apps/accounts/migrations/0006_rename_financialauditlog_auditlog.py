"""Rename FinancialAuditLog → AuditLog in place.

A rename, not a delete-and-create: the table (accounts_financial_audit_log is
pinned in Meta.db_table) and every row already in it are kept.
"""
from django.conf import settings
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("accounts", "0005_backfill_user_roles"),
    ]

    operations = [
        migrations.RenameModel("FinancialAuditLog", "AuditLog"),
    ]
