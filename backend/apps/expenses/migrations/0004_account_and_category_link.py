"""Add Chart of Accounts (Account) + link ExpenseCategory to expense accounts.

Schema:
    - new Account table with the 22 codes from the proposed Wilkem Ventures COA
    - new nullable Account FK on ExpenseCategory

Data:
    - seed all 22 accounts (1010, 1020, 1200, 1210, 2100, 2200, 3010, 3020,
      4000, 4010, 5010, 5020, 5030, 5040, 5050, 5060, 5070, 5080, 5090, 5100)
    - map the 9 seeded ExpenseCategory rows to the closest expense account
"""
import django.db.models.deletion
from django.db import migrations, models


SEED_ACCOUNTS = [
    # ASSETS (1xxx)
    ("1010", "Checking - Operating",        "asset",     "Main business checking account."),
    ("1020", "Checking - Security Deposits","asset",     "Restricted account for tenant deposits."),
    ("1200", "Building Cost",               "asset",     "Original purchase price of the structure."),
    ("1210", "Land Cost",                   "asset",     "Value of the land (non-depreciable)."),
    # LIABILITIES (2xxx)
    ("2100", "Security Deposits Held",      "liability", "Funds owed back to tenants."),
    ("2200", "Mortgage Payable",            "liability", "Principal balance of property loan."),
    # EQUITY (3xxx)
    ("3010", "Owner's Contribution",        "equity",    "Personal funds added to the business."),
    ("3020", "Owner's Draw",                "equity",    "Funds withdrawn for personal use."),
    # INCOME (4xxx)
    ("4000", "Rental Income",               "income",    "Monthly rent payments."),
    ("4010", "Late Fees",                   "income",    "Fees for overdue payments."),
    # EXPENSES (5xxx)
    ("5010", "Advertising",                 "expense",   "Marketing for vacancies."),
    ("5020", "Auto & Travel",               "expense",   "Mileage and travel for property visits."),
    ("5030", "Insurance",                   "expense",   "Property and liability insurance."),
    ("5040", "Legal & Professional Fees",   "expense",   "CPA, attorney, or eviction costs."),
    ("5050", "Management Fees",             "expense",   "Fees paid to property managers."),
    ("5060", "Mortgage Interest",           "expense",   "Interest paid on loans."),
    ("5070", "Repairs & Maintenance",       "expense",   "Routine upkeep (painting, plumbing, etc.)."),
    ("5080", "Supplies",                    "expense",   "Items purchased for property use."),
    ("5090", "Taxes - Property",            "expense",   "Real estate taxes / land rates / rents."),
    ("5100", "Utilities",                   "expense",   "Water, gas, electricity paid by the owner."),
]

# Map the names seeded by buildings.seed_reports_data → expense account code.
CATEGORY_TO_CODE = {
    "Maintenance":         "5070",
    "Utilities":           "5100",
    "Security":            "5070",  # guard salary / CCTV → maintenance
    "Cleaning":            "5070",
    "Repairs":             "5070",
    "Water":               "5100",
    "Electricity":         "5100",
    "Garbage Collection":  "5100",
    "Management Fee":      "5050",
}


def seed_accounts_and_link_categories(apps, schema_editor):
    Account = apps.get_model("expenses", "Account")
    ExpenseCategory = apps.get_model("expenses", "ExpenseCategory")

    for code, name, account_type, description in SEED_ACCOUNTS:
        Account.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "account_type": account_type,
                "description": description,
                "is_active": True,
            },
        )

    by_code = {a.code: a for a in Account.objects.all()}
    for cat in ExpenseCategory.objects.filter(account__isnull=True):
        target_code = CATEGORY_TO_CODE.get(cat.name)
        if target_code and target_code in by_code:
            cat.account = by_code[target_code]
            cat.save(update_fields=["account"])


def unlink_categories(apps, schema_editor):
    ExpenseCategory = apps.get_model("expenses", "ExpenseCategory")
    ExpenseCategory.objects.update(account=None)


class Migration(migrations.Migration):

    dependencies = [
        ("expenses", "0003_expense_building_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="Account",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(help_text="4-digit GL code (e.g. 5070).", max_length=8, unique=True)),
                ("name", models.CharField(max_length=120)),
                ("account_type", models.CharField(
                    choices=[
                        ("asset", "Asset"),
                        ("liability", "Liability"),
                        ("equity", "Equity"),
                        ("income", "Income"),
                        ("expense", "Expense"),
                    ],
                    max_length=10,
                )),
                ("description", models.CharField(blank=True, max_length=255)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "accounting_account",
                "ordering": ["code"],
            },
        ),
        migrations.AddField(
            model_name="expensecategory",
            name="account",
            field=models.ForeignKey(
                blank=True,
                help_text="GL account this category posts to (5010-5100).",
                limit_choices_to={"account_type": "expense"},
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="expense_categories",
                to="expenses.account",
            ),
        ),
        migrations.RunPython(seed_accounts_and_link_categories, unlink_categories),
    ]
