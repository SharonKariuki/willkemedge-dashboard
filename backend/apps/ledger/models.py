"""
General Ledger models.

JournalEntry  — the transaction header (one per financial event).
JournalLine   — the individual debit / credit legs.

Every saved JournalEntry must balance: Σdebit == Σcredit across its lines.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models

from apps.expenses.models import Account


class JournalEntry(models.Model):
    """Header for a balanced double-entry journal transaction."""

    date = models.DateField()
    period_month = models.PositiveSmallIntegerField(editable=False)
    period_year = models.PositiveIntegerField(editable=False)
    memo = models.CharField(max_length=255)
    reference = models.CharField(max_length=100, blank=True)

    building = models.ForeignKey(
        "buildings.Building",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="journal_entries",
    )

    # Generic FK pair — we store type as a string label ("payment", "expense")
    # and id as a positive integer so we avoid the contenttypes overhead while
    # still being able to trace every posting back to its source row.
    source_type = models.CharField(max_length=30, blank=True)
    source_id = models.PositiveIntegerField(null=True, blank=True)

    # kind distinguishes NORMAL from REVERSAL entries for the same source row.
    kind = models.CharField(
        max_length=10,
        choices=[("normal", "Normal"), ("reversal", "Reversal")],
        default="normal",
    )

    is_posted = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ledger_journal_entry"
        ordering = ["-date", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["source_type", "source_id", "kind"],
                name="unique_journal_entry_per_source_kind",
            )
        ]
        indexes = [
            models.Index(fields=["period_year", "period_month"]),
            models.Index(fields=["building", "period_year", "period_month"]),
            models.Index(fields=["source_type", "source_id"]),
        ]

    def save(self, *args, **kwargs):
        # Derive period from date
        self.period_month = self.date.month
        self.period_year = self.date.year
        super().save(*args, **kwargs)

    def clean(self):
        """Assert the entry balances — called explicitly; not auto-called on save."""
        lines = list(self.lines.all()) if self.pk else []
        if lines:
            total_debit = sum(line.debit for line in lines)
            total_credit = sum(line.credit for line in lines)
            if total_debit != total_credit:
                raise ValidationError(
                    f"Journal entry does not balance: "
                    f"debits={total_debit} credits={total_credit}"
                )

    def assert_balanced(self, lines):
        """Check a list of unsaved JournalLine objects balance before saving."""
        total_debit = sum(line.debit for line in lines)
        total_credit = sum(line.credit for line in lines)
        if total_debit != total_credit:
            raise ValidationError(
                f"Journal entry does not balance: "
                f"debits={total_debit} credits={total_credit}"
            )

    def __str__(self):
        return f"JE-{self.pk} {self.date} {self.memo}"


class JournalLine(models.Model):
    """A single debit or credit leg of a journal entry."""

    entry = models.ForeignKey(
        JournalEntry,
        on_delete=models.CASCADE,
        related_name="lines",
    )
    account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name="journal_lines",
        limit_choices_to={"is_header": False},
    )
    debit = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    credit = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    description = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "ledger_journal_line"
        constraints = [
            # Never allow both debit and credit to be > 0 on the same line
            models.CheckConstraint(
                condition=~(models.Q(debit__gt=0) & models.Q(credit__gt=0)),
                name="ledger_line_not_both_sides",
            ),
            # At least one side must be > 0
            models.CheckConstraint(
                condition=models.Q(debit__gt=0) | models.Q(credit__gt=0),
                name="ledger_line_nonzero",
            ),
        ]

    def __str__(self):
        side = f"DR {self.debit}" if self.debit else f"CR {self.credit}"
        return f"{self.account.code} {side}"


class Budget(models.Model):
    """Per-account monthly budget for variance reporting."""

    account = models.ForeignKey(
        Account,
        on_delete=models.CASCADE,
        related_name="budgets",
        limit_choices_to={"is_header": False},
    )
    building = models.ForeignKey(
        "buildings.Building",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="budgets",
    )
    period_month = models.PositiveSmallIntegerField()
    period_year = models.PositiveIntegerField()
    amount = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        db_table = "ledger_budget"
        constraints = [
            models.UniqueConstraint(
                fields=["account", "building", "period_month", "period_year"],
                name="unique_budget_per_account_period",
            )
        ]

    def __str__(self):
        return f"Budget {self.account.code} {self.period_month}/{self.period_year} = {self.amount}"
