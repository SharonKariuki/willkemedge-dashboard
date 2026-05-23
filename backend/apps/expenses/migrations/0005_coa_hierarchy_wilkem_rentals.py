"""Adopt the Wilkem Ventures Rentals & Commercials Chart of Accounts.

Schema:
    - add ``parent_code`` (section header roll-up) and ``is_header`` to Account
    - widen ExpenseCategory.account choices to any non-header expense account

Data:
    - seed the full COA: 6 section headers + 46 posting accounts
    - repoint the existing seeded ExpenseCategory rows to the closest new code
      (expenses link through categories, so no expense data is touched)
    - drop the old US-style codes that are no longer part of the chart
"""
import django.db.models.deletion
from django.db import migrations, models


# (code, name, account_type, parent_code, is_header, description)
HEADERS = [
    ("1000", "Assets",                    "asset",     "", True, ""),
    ("2000", "Liabilities",               "liability", "", True, ""),
    ("3000", "Equity",                    "equity",    "", True, ""),
    ("4000", "Income / Revenue",          "income",    "", True, ""),
    ("5000", "Operating Expenses",        "expense",   "", True, ""),
    ("6000", "Fixed and Non-Operating Costs", "expense", "", True, ""),
]

ACCOUNTS = [
    # ── Assets (1000) ────────────────────────────────────────────────────────
    ("1010", "Petty Cash",                         "asset", "1000", "On-hand cash float for small disbursements."),
    ("1020", "Operating Bank Account",             "asset", "1000", "Main business bank account (KES)."),
    ("1030", "Tenant Security Deposit Bank Account","asset", "1000", "Restricted account holding tenant deposits."),
    ("1040", "Accounts Receivable (Rent Arrears)", "asset", "1000", "Rent billed but not yet collected."),
    ("1050", "Prepaid Expenses",                   "asset", "1000", "Costs paid in advance (e.g. prepaid insurance)."),
    ("1060", "Investment Property / Land",         "asset", "1000", "Value of land held (non-depreciable)."),
    ("1350", "Buildings & Improvements",           "asset", "1000", "Capitalised cost of structures and improvements."),
    ("1360", "Accumulated Depreciation",           "asset", "1000", "Contra-asset: depreciation accrued to date."),
    ("1370", "Furniture & Office Equipment",       "asset", "1000", "Capitalised furniture and equipment."),
    # ── Liabilities (2000) ───────────────────────────────────────────────────
    ("2010", "Accounts Payable (Suppliers/Contractors)", "liability", "2000", "Amounts owed to suppliers and contractors."),
    ("2020", "Accrued Expenses",                   "liability", "2000", "Incurred but unpaid expenses."),
    ("2100", "Tenant Security Deposits Held",      "liability", "2000", "Deposits owed back to tenants."),
    ("2500", "Mortgages Payable / Bank Loans",     "liability", "2000", "Outstanding principal on property loans."),
    ("2600", "VAT Payable",                        "liability", "2000", "VAT collected and owed to KRA."),
    ("2700", "PAYE Payable",                       "liability", "2000", "Pay As You Earn withheld from staff."),
    ("2800", "NSSF/NHIF Payables",                 "liability", "2000", "Statutory payroll deductions owed."),
    # ── Equity (3000) ────────────────────────────────────────────────────────
    ("3100", "Owner's Capital / Share Capital",    "equity", "3000", "Capital contributed by owners/shareholders."),
    ("3200", "Owner's Drawings / Dividends",       "equity", "3000", "Funds withdrawn or distributed to owners."),
    ("3300", "Retained Earnings",                  "equity", "3000", "Accumulated undistributed profits."),
    # ── Income / Revenue (4000) ──────────────────────────────────────────────
    ("4110", "Residential Rental Income",          "income", "4000", "Rent from residential units."),
    ("4120", "Commercial Rental Income",           "income", "4000", "Rent from commercial units."),
    ("4150", "Service Charge / Utilities Reimbursed by Tenants", "income", "4000", "Utility and service costs recovered from tenants."),
    ("4200", "Late Payment Fees / Penalties",      "income", "4000", "Penalties charged on overdue rent."),
    ("4250", "Parking Fees",                       "income", "4000", "Income from parking allocations."),
    # ── Operating Expenses (5000) ──────────────────────────────────────────────
    ("5100", "Property Management Fees",           "expense", "5000", "Fees paid to property managers."),
    ("5200", "Repairs & Maintenance",              "expense", "5000", "Routine upkeep and repairs."),
    ("5210", "Plumbing & Electrical",              "expense", "5000", "Plumbing and electrical works."),
    ("5220", "Cleaning & Garbage Collection",      "expense", "5000", "Cleaning and waste removal."),
    ("5230", "Gardening & Landscaping",            "expense", "5000", "Grounds and landscaping upkeep."),
    ("5300", "Utilities (Common Areas)",           "expense", "5000", "Water & electricity for common areas."),
    ("5400", "Marketing & Advertising",            "expense", "5000", "Vacancy advertising and marketing."),
    ("5500", "Legal & Professional Fees",          "expense", "5000", "Legal, audit and professional fees."),
    ("5600", "Security Services",                  "expense", "5000", "Guarding, CCTV and security."),
    ("5700", "Property Management Software",        "expense", "5000", "Software subscriptions for management."),
    ("5800", "Caretaking Services",                "expense", "5000", "Caretaker and on-site staff costs."),
    ("5900", "Travel and Vehicle Expenses",        "expense", "5000", "Mileage and travel for property visits."),
    ("5910", "Salaries and Wages",                 "expense", "5000", "Staff salaries and wages."),
    ("5920", "Office Expenses",                    "expense", "5000", "General office running costs."),
    ("5930", "Commissions",                        "expense", "5000", "Letting and agent commissions."),
    ("5940", "Bank Fees",                          "expense", "5000", "Bank charges and transaction fees."),
    # ── Fixed and Non-Operating Costs (6000) ────────────────────────────────────
    ("6100", "Insurance",                          "expense", "6000", "Property and liability insurance."),
    ("6200", "Property Taxes - Land Rates",        "expense", "6000", "Land rates paid to County Government."),
    ("6300", "Property Taxes - Land Rent",         "expense", "6000", "Land rent payable."),
    ("6400", "Interest Expense (Mortgages)",       "expense", "6000", "Interest on property loans."),
    ("6500", "Corporate Tax",                      "expense", "6000", "Corporation tax on profits."),
    ("6600", "Depreciation Expense",               "expense", "6000", "Periodic depreciation charge."),
]

# Old seeded ExpenseCategory names → new expense GL code.
CATEGORY_TO_CODE = {
    "Maintenance":        "5200",
    "Repairs":            "5200",
    "Utilities":          "5300",
    "Water":              "5300",
    "Electricity":        "5300",
    "Cleaning":           "5220",
    "Garbage Collection": "5220",
    "Security":           "5600",
    "Management Fee":     "5100",
}

NEW_CODES = {row[0] for row in HEADERS} | {row[0] for row in ACCOUNTS}


def seed_coa(apps, schema_editor):
    Account = apps.get_model("expenses", "Account")
    ExpenseCategory = apps.get_model("expenses", "ExpenseCategory")

    # 1. Seed headers + posting accounts (idempotent on code).
    for code, name, account_type, parent_code, is_header, description in HEADERS:
        Account.objects.update_or_create(
            code=code,
            defaults={
                "name": name, "account_type": account_type,
                "parent_code": parent_code, "is_header": is_header,
                "description": description, "is_active": True,
            },
        )
    for code, name, account_type, parent_code, description in ACCOUNTS:
        Account.objects.update_or_create(
            code=code,
            defaults={
                "name": name, "account_type": account_type,
                "parent_code": parent_code, "is_header": False,
                "description": description, "is_active": True,
            },
        )

    # 2. Repoint existing categories to the new codes (expenses ride along).
    by_code = {a.code: a for a in Account.objects.all()}
    for cat in ExpenseCategory.objects.all():
        target = CATEGORY_TO_CODE.get(cat.name)
        if target and target in by_code:
            cat.account = by_code[target]
            cat.save(update_fields=["account"])

    # 3. Drop the old codes no longer in the chart (now unreferenced).
    Account.objects.exclude(code__in=NEW_CODES).delete()


def unseed_coa(apps, schema_editor):
    """Reverse: detach categories and remove the seeded COA rows."""
    Account = apps.get_model("expenses", "Account")
    ExpenseCategory = apps.get_model("expenses", "ExpenseCategory")
    ExpenseCategory.objects.filter(account__code__in=NEW_CODES).update(account=None)
    Account.objects.filter(code__in=NEW_CODES).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("expenses", "0004_account_and_category_link"),
    ]

    operations = [
        migrations.AddField(
            model_name="account",
            name="parent_code",
            field=models.CharField(
                blank=True,
                help_text="Section header this account rolls up to (e.g. 5000). Blank for headers themselves.",
                max_length=8,
            ),
        ),
        migrations.AddField(
            model_name="account",
            name="is_header",
            field=models.BooleanField(
                default=False,
                help_text="True for section headers (1000/2000/…) that group postings but hold no balance.",
            ),
        ),
        migrations.AlterField(
            model_name="expensecategory",
            name="account",
            field=models.ForeignKey(
                blank=True,
                help_text="GL account this category posts to (5100-6600).",
                limit_choices_to={"account_type": "expense", "is_header": False},
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="expense_categories",
                to="expenses.account",
            ),
        ),
        migrations.RunPython(seed_coa, unseed_coa),
    ]
