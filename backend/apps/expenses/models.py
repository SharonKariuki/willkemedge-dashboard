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
    """A single row in the Chart of Accounts."""

    code = models.CharField(max_length=8, unique=True, help_text="4-digit GL code (e.g. 5070).")
    name = models.CharField(max_length=120)
    account_type = models.CharField(max_length=10, choices=AccountType.choices)
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
        limit_choices_to={"account_type": AccountType.EXPENSE},
        help_text="GL account this category posts to (5010-5100).",
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
