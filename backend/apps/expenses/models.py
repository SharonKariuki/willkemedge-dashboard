"""
Expense tracking + Chart of Accounts.

Account: a row in the chart of accounts (e.g. 5070 Repairs & Maintenance).
ExpenseCategory: reusable tag the user picks when recording an expense;
    each category maps to one expense Account so the P&L groups by GL code.
Expense: an immutable financial record of money spent.
"""
from django.db import models


class AccountType(models.TextChoices):
    ASSET = "asset", "Asset"
    LIABILITY = "liability", "Liability"
    EQUITY = "equity", "Equity"
    INCOME = "income", "Income"
    EXPENSE = "expense", "Expense"


class Account(models.Model):
    """A single row in the Chart of Accounts.

    The Wilkem Ventures COA is a two-level hierarchy: section headers
    (1000 ASSETS, 5000 OPERATING EXPENSES, …) carry ``is_header=True`` and
    no balance; each posting account hangs off a header via ``parent_code``.
    """

    code = models.CharField(max_length=8, unique=True, help_text="GL code (e.g. 5200 Repairs & Maintenance).")
    name = models.CharField(max_length=120)
    account_type = models.CharField(max_length=10, choices=AccountType.choices)
    parent_code = models.CharField(
        max_length=8,
        blank=True,
        help_text="Section header this account rolls up to (e.g. 5000). Blank for headers themselves.",
    )
    is_header = models.BooleanField(
        default=False,
        help_text="True for section headers (1000/2000/…) that group postings but hold no balance.",
    )
    description = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "accounting_account"
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"


class ExpenseCategory(models.Model):
    """A named bucket for grouping expenses; maps to one expense Account."""

    name = models.CharField(max_length=100, unique=True)
    description = models.CharField(max_length=255, blank=True)
    account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="expense_categories",
        limit_choices_to={"account_type": AccountType.EXPENSE, "is_header": False},
        help_text="GL account this category posts to (5100-6600).",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "expenses_category"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Expense(models.Model):
    """An immutable record of money spent on property operations."""

    date = models.DateField(help_text="Date the expense was incurred.")
    building = models.ForeignKey(
        "buildings.Building",
        on_delete=models.PROTECT,
        related_name="expenses",
        null=True,
        blank=True,
        help_text="Building this expense applies to. Leave blank for portfolio-wide costs.",
    )
    category = models.ForeignKey(
        ExpenseCategory,
        on_delete=models.PROTECT,
        related_name="expenses",
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.CharField(max_length=500)
    reference = models.CharField(
        max_length=100,
        blank=True,
        help_text="Receipt number, invoice ref, etc.",
    )
    period_month = models.PositiveSmallIntegerField(
        help_text="Month the expense applies to (1-12).",
    )
    period_year = models.PositiveIntegerField(
        help_text="Year the expense applies to.",
    )
    notes = models.TextField(blank=True)

    class PaymentMethod(models.TextChoices):
        BANK = "bank", "Bank / MPESA"
        PETTY_CASH = "petty_cash", "Petty Cash"

    payment_method = models.CharField(
        max_length=10,
        choices=PaymentMethod.choices,
        default=PaymentMethod.BANK,
        help_text="How this expense was paid — determines whether 1020 (bank) or 1010 (petty cash) is credited.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "expenses_expense"
        ordering = ["-date", "-created_at"]
        indexes = [
            models.Index(fields=["period_year", "period_month"]),
            models.Index(fields=["category"]),
            models.Index(fields=["building"]),
        ]

    def __str__(self) -> str:
        return f"{self.category.name} — KES {self.amount} ({self.period_month}/{self.period_year})"


class ManualIncome(models.Model):
    """Non-tenant income recorded by hand — e.g. farm produce sales.

    Rent flows through Payment (which requires a tenant + unit). Income from
    farms (FSE/FMM/FNN) has no tenant, so it is recorded here and posts to the
    ledger against a chosen INCOME account. Expense-only properties (Baobab
    Karen / KRN) may NOT record income — enforced in the serializer.
    """

    date = models.DateField(help_text="Date the income was received.")
    building = models.ForeignKey(
        "buildings.Building",
        on_delete=models.PROTECT,
        related_name="manual_income",
        help_text="Property this income belongs to (a farm).",
    )
    account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name="manual_income",
        limit_choices_to={"account_type": AccountType.INCOME, "is_header": False},
        help_text="GL income account this posts to (4xxx).",
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    description = models.CharField(max_length=500)
    reference = models.CharField(max_length=100, blank=True)
    period_month = models.PositiveSmallIntegerField()
    period_year = models.PositiveIntegerField()
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "expenses_manual_income"
        ordering = ["-date", "-created_at"]
        indexes = [
            models.Index(fields=["period_year", "period_month"]),
            models.Index(fields=["building"]),
        ]

    def __str__(self) -> str:
        return f"{self.description} — KES {self.amount} ({self.period_month}/{self.period_year})"
