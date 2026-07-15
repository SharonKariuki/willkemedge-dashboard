"""
Canonical Chart of Accounts — the single source of truth for the Wilkem
Ventures Rentals & Commercials chart.

The chart was first seeded by migration
``0005_coa_hierarchy_wilkem_rentals`` (which, like all migrations, carries a
frozen copy). This module holds the *live* definition so application code and
the ``seed_coa`` management command can re-seed or verify the chart on an
existing database without replaying a migration.

Keep this in step with the COA document. Anything referencing a GL code should
import from here rather than hardcoding a string.
"""

# (code, name, account_type, parent_code, is_header, description)
HEADERS = [
    ("1000", "Assets",                            "asset",     "", True, ""),
    ("2000", "Liabilities",                       "liability", "", True, ""),
    ("3000", "Equity",                            "equity",    "", True, ""),
    ("4000", "Income / Revenue",                  "income",    "", True, ""),
    ("5000", "Operating Expenses",                "expense",   "", True, ""),
    ("6000", "Fixed and Non-Operating Costs",     "expense",   "", True, ""),
]

# (code, name, account_type, parent_code, description)
ACCOUNTS = [
    # ── Assets (1000) ────────────────────────────────────────────────────────
    ("1010", "Petty Cash",                          "asset", "1000", "On-hand cash float for small disbursements."),
    ("1020", "Operating Bank Account",              "asset", "1000", "Main business bank account (KES)."),
    ("1030", "Tenant Security Deposit Bank Account", "asset", "1000", "Restricted account holding tenant deposits."),
    ("1040", "Accounts Receivable (Rent Arrears)",  "asset", "1000", "Rent billed but not yet collected."),
    ("1050", "Prepaid Expenses",                    "asset", "1000", "Costs paid in advance (e.g. prepaid insurance)."),
    ("1060", "Investment Property / Land",          "asset", "1000", "Value of land held (non-depreciable)."),
    ("1350", "Buildings & Improvements",            "asset", "1000", "Capitalised cost of structures and improvements."),
    ("1360", "Accumulated Depreciation",            "asset", "1000", "Contra-asset: depreciation accrued to date."),
    ("1370", "Furniture & Office Equipment",        "asset", "1000", "Capitalised furniture and equipment."),
    # ── Liabilities (2000) ───────────────────────────────────────────────────
    ("2010", "Accounts Payable (Suppliers/Contractors)", "liability", "2000", "Amounts owed to suppliers and contractors."),
    ("2020", "Accrued Expenses",                    "liability", "2000", "Incurred but unpaid expenses."),
    ("2100", "Tenant Security Deposits Held",       "liability", "2000", "Deposits owed back to tenants."),
    ("2500", "Mortgages Payable / Bank Loans",      "liability", "2000", "Outstanding principal on property loans."),
    ("2600", "VAT Payable",                         "liability", "2000", "VAT collected and owed to KRA."),
    ("2700", "PAYE Payable",                        "liability", "2000", "Pay As You Earn withheld from staff."),
    ("2800", "NSSF/NHIF Payables",                  "liability", "2000", "Statutory payroll deductions owed."),
    # ── Equity (3000) ────────────────────────────────────────────────────────
    ("3100", "Owner's Capital / Share Capital",     "equity", "3000", "Capital contributed by owners/shareholders."),
    ("3200", "Owner's Drawings / Dividends",        "equity", "3000", "Funds withdrawn or distributed to owners."),
    ("3300", "Retained Earnings",                   "equity", "3000", "Accumulated undistributed profits."),
    # ── Income / Revenue (4000) ──────────────────────────────────────────────
    ("4110", "Residential Rental Income",           "income", "4000", "Rent from residential units."),
    ("4120", "Commercial Rental Income",            "income", "4000", "Rent from commercial units."),
    ("4150", "Service Charge / Utilities Reimbursed by Tenants", "income", "4000", "Utility and service costs recovered from tenants."),
    ("4200", "Late Payment Fees / Penalties",       "income", "4000", "Penalties charged on overdue rent."),
    ("4250", "Parking Fees",                        "income", "4000", "Income from parking allocations."),
    # ── Operating Expenses (5000) ────────────────────────────────────────────
    ("5100", "Property Management Fees",            "expense", "5000", "Fees paid to property managers."),
    ("5200", "Repairs & Maintenance",               "expense", "5000", "Routine upkeep and repairs."),
    ("5210", "Plumbing & Electrical",               "expense", "5000", "Plumbing and electrical works."),
    ("5220", "Cleaning & Garbage Collection",       "expense", "5000", "Cleaning and waste removal."),
    ("5230", "Gardening & Landscaping",             "expense", "5000", "Grounds and landscaping upkeep."),
    ("5300", "Utilities (Common Areas)",            "expense", "5000", "Water & electricity for common areas."),
    ("5400", "Marketing & Advertising",             "expense", "5000", "Vacancy advertising and marketing."),
    ("5500", "Legal & Professional Fees",           "expense", "5000", "Legal, audit and professional fees."),
    ("5600", "Security Services",                   "expense", "5000", "Guarding, CCTV and security."),
    ("5700", "Property Management Software",        "expense", "5000", "Software subscriptions for management."),
    ("5800", "Caretaking Services",                 "expense", "5000", "Caretaker and on-site staff costs."),
    ("5900", "Travel and Vehicle Expenses",         "expense", "5000", "Mileage and travel for property visits."),
    ("5910", "Salaries and Wages",                  "expense", "5000", "Staff salaries and wages."),
    ("5920", "Office Expenses",                     "expense", "5000", "General office running costs."),
    ("5930", "Commissions",                         "expense", "5000", "Letting and agent commissions."),
    ("5940", "Bank Fees",                           "expense", "5000", "Bank charges and transaction fees."),
    # ── Fixed and Non-Operating Costs (6000) ─────────────────────────────────
    ("6100", "Insurance",                           "expense", "6000", "Property and liability insurance."),
    ("6200", "Property Taxes - Land Rates",         "expense", "6000", "Land rates paid to County Government."),
    ("6300", "Property Taxes - Land Rent",          "expense", "6000", "Land rent payable."),
    ("6400", "Interest Expense (Mortgages)",        "expense", "6000", "Interest on property loans."),
    ("6500", "Corporate Tax",                       "expense", "6000", "Corporation tax on profits."),
    ("6600", "Depreciation Expense",                "expense", "6000", "Periodic depreciation charge."),
]

CHART_CODES = {row[0] for row in HEADERS} | {row[0] for row in ACCOUNTS}

# ── Expense categories, each LOCKED to one GL code ───────────────────────────
# This is the fixed dropdown staff choose from. A category always posts to its
# mapped account — there is no free-text GL entry anywhere in the system.
# (name, gl_code)
EXPENSE_CATEGORIES = [
    ("Property Management Fees",        "5100"),
    ("Repairs & Maintenance",           "5200"),
    ("Plumbing & Electrical",           "5210"),
    ("Cleaning & Garbage Collection",   "5220"),
    ("Gardening & Landscaping",         "5230"),
    ("Utilities (Common Areas)",        "5300"),
    ("Marketing & Advertising",         "5400"),
    ("Legal & Professional Fees",       "5500"),
    ("Security Services",               "5600"),
    ("Property Management Software",    "5700"),
    ("Caretaking Services",             "5800"),
    ("Travel and Vehicle Expenses",     "5900"),
    ("Salaries and Wages",              "5910"),
    ("Office Expenses",                 "5920"),
    ("Commissions",                     "5930"),
    ("Bank Fees",                       "5940"),
    ("Insurance",                       "6100"),
    ("Property Taxes - Land Rates",     "6200"),
    ("Property Taxes - Land Rent",      "6300"),
    ("Interest Expense (Mortgages)",    "6400"),
    ("Corporate Tax",                   "6500"),
    ("Depreciation Expense",            "6600"),
]

# Legacy free-text category names (lower-cased) → the GL code they belong to.
# Used to repair pre-existing rows that were created before categories were
# locked; without a code, their expenses never reach the ledger.
LEGACY_CATEGORY_TO_CODE = {
    "repairs":            "5200",
    "maintenance":        "5200",
    "repairs & maintenance": "5200",
    "utilities":          "5300",
    "water":              "5300",
    "electricity":        "5300",
    "cleaning":           "5220",
    "garbage collection": "5220",
    "security":           "5600",
    "management fee":     "5100",
    "insurance":          "6100",
    "legal":              "5500",
    "salaries":           "5910",
}

# ── Named codes used by posting logic (import these, never hardcode) ─────────
RENT_RESIDENTIAL = "4110"
RENT_COMMERCIAL = "4120"
SERVICE_CHARGE_UTILITIES = "4150"   # water / "Other Charges" recovered from tenants
LATE_FEES = "4200"
PARKING = "4250"
VAT_PAYABLE = "2600"                # 16% VAT collected on commercial rent
DEPOSITS_HELD = "2100"
RENT_RECEIVABLE = "1040"
