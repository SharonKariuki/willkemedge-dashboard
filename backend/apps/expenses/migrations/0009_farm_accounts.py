"""Add farm accounts to the Chart of Accounts.

The Wilkem Ventures chart is rentals/commercials-focused, but the company also
runs farm properties (Nyamira x2, Soy). Farm produce income (recorded via
Manual Income) and farm operating costs (seeds, fertiliser, feed) had no GL
home, so they could only be mis-booked as rent or shoehorned into an unrelated
expense category. These two codes — already present as line items in the
audited financial statements ("Other income - farm", "Farm Inputs") — give them
a proper home:

    4300  Farm / Agricultural Income   (income,  under 4000)
    5950  Farm Inputs / Operating Costs (expense, under 5000) + locked category

Data-only + idempotent (mirrors the seed_coa pattern), so it is safe on any
existing database.
"""
from django.db import migrations

# (code, name, account_type, parent_code, description) — frozen copy.
NEW_ACCOUNTS = [
    ("4300", "Farm / Agricultural Income", "income", "4000",
     "Farm produce and agricultural income (non-tenant, e.g. Nyamira/Soy farms). Recorded via Manual Income."),
    ("5950", "Farm Inputs / Operating Costs", "expense", "5000",
     "Seeds, fertiliser, feed, and other farm operating inputs."),
]

# Locked expense category → GL code (matches EXPENSE_CATEGORIES in coa.py).
NEW_CATEGORY = ("Farm Inputs / Operating Costs", "5950")


def add_farm_accounts(apps, schema_editor):
    Account = apps.get_model("expenses", "Account")
    ExpenseCategory = apps.get_model("expenses", "ExpenseCategory")

    for code, name, account_type, parent_code, description in NEW_ACCOUNTS:
        Account.objects.update_or_create(
            code=code,
            defaults={
                "name": name, "account_type": account_type,
                "parent_code": parent_code, "is_header": False,
                "description": description, "is_active": True,
            },
        )

    cat_name, cat_code = NEW_CATEGORY
    account = Account.objects.filter(code=cat_code).first()
    if account is not None:
        ExpenseCategory.objects.update_or_create(
            name=cat_name, defaults={"account": account},
        )


def remove_farm_accounts(apps, schema_editor):
    Account = apps.get_model("expenses", "Account")
    ExpenseCategory = apps.get_model("expenses", "ExpenseCategory")

    cat_name, _ = NEW_CATEGORY
    # Detach then delete the category only if it carries no expenses (PROTECT).
    ExpenseCategory.objects.filter(name=cat_name, expenses__isnull=True).delete()
    ExpenseCategory.objects.filter(name=cat_name).update(account=None)

    for code, *_ in NEW_ACCOUNTS:
        # PROTECT on journal_lines will block deletion if the account was used —
        # that is intentional: never drop an account that already carries postings.
        Account.objects.filter(code=code, journal_lines__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("expenses", "0008_manualincome"),
    ]

    operations = [
        migrations.RunPython(add_farm_accounts, remove_farm_accounts),
    ]
