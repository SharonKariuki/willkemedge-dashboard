"""
Expense tracking models.

ExpenseCategory: reusable tags (Repairs, Security, Water, etc.)
Expense: an immutable financial record of money spent.
"""
from django.db import models


class ExpenseCategory(models.Model):
    """A named bucket for grouping expenses."""

    name = models.CharField(max_length=100, unique=True)
    description = models.CharField(max_length=255, blank=True)
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
