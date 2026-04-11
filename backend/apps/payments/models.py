"""
Payment and Arrears models.

Payments are immutable financial records. Once created, they are never
soft-deleted or modified. Only the admin can void a payment by creating
a reverse entry.

Arrears track outstanding balances per tenant per month.
"""
from django.db import models

from apps.tenants.models import Tenant


class PaymentSource(models.TextChoices):
    MPESA = "mpesa", "M-Pesa"
    BANK = "bank", "Bank Transfer"
    CASH = "cash", "Cash"
    CHEQUE = "cheque", "Cheque"


class Payment(models.Model):
    """An immutable financial record of money received."""

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.PROTECT,
        related_name="payments",
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_date = models.DateField()
    period_month = models.PositiveSmallIntegerField(
        help_text="Month the payment applies to (1-12).",
    )
    period_year = models.PositiveIntegerField(
        help_text="Year the payment applies to.",
    )
    source = models.CharField(
        max_length=10,
        choices=PaymentSource.choices,
        default=PaymentSource.CASH,
    )
    reference = models.CharField(
        max_length=100,
        blank=True,
        help_text="M-Pesa TransID, bank ref, or receipt number.",
    )
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "payments_payment"
        ordering = ["-payment_date", "-created_at"]
        indexes = [
            models.Index(fields=["tenant", "period_year", "period_month"]),
            models.Index(fields=["reference"]),
        ]

    def __str__(self) -> str:
        return f"KES {self.amount} — {self.tenant} ({self.period_month}/{self.period_year})"


class Arrears(models.Model):
    """Outstanding balance for a tenant in a given period."""

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.PROTECT,
        related_name="arrears",
    )
    period_month = models.PositiveSmallIntegerField()
    period_year = models.PositiveIntegerField()
    expected_rent = models.DecimalField(max_digits=10, decimal_places=2)
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    balance = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="expected_rent - amount_paid. Positive = owed.",
    )
    is_cleared = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "payments_arrears"
        ordering = ["-period_year", "-period_month"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "period_month", "period_year"],
                name="unique_arrears_per_period",
            ),
        ]

    def __str__(self) -> str:
        status = "cleared" if self.is_cleared else f"KES {self.balance} owed"
        return f"{self.tenant} — {self.period_month}/{self.period_year} ({status})"
