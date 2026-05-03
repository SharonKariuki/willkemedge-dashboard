"""
Payment and Arrears models.

Payments are immutable financial records. Once created, they are never
soft-deleted or modified. Only the admin can void a payment by creating
a reverse entry.

Arrears track outstanding balances per tenant per month.

Transaction is the auditable financial record that stores every tax-derived
value at write time so reads never recalculate derived figures.
"""
from django.conf import settings
from django.db import models

from apps.buildings.models import UnitClassification
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
    waived_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    waive_notes = models.TextField(blank=True)


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


# ---------------------------------------------------------------------------
# Transaction — immutable VAT-aware financial record
# ---------------------------------------------------------------------------

class PaymentMode(models.TextChoices):
    """Subset of PaymentSource allowed for Transaction records (webhook-grade)."""
    MPESA = "MPESA", "M-Pesa"
    BANK = "BANK", "Bank Transfer"
    CASH = "CASH", "Cash"
    CHEQUE = "CHEQUE", "Cheque"


class Transaction(models.Model):
    """
    Immutable, VAT-aware financial record created for every payment event.

    Design rules
    ------------
    1. Created once; never updated or deleted.
    2. All derived values (tax_amount, total_amount) are stored at write time.
       Reads MUST NOT recalculate them.
    3. transaction_id is a system-generated unique identifier for traceability.
    4. reference_code is stored exactly as received from the payment gateway.
    5. unit_classification is snapshotted from the unit at transaction time so
       historical records remain accurate if the unit's classification changes.
    """

    # --- Identifiers ---
    transaction_id = models.CharField(
        max_length=40,
        unique=True,
        editable=False,
        help_text="System-generated unique transaction identifier (TXN-<uuid4_hex[:16]>).",
    )

    # --- Relationships (FK; kept for join queries) ---
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.PROTECT,
        related_name="transactions",
    )
    payment = models.OneToOneField(
        Payment,
        on_delete=models.PROTECT,
        related_name="transaction",
        help_text="The underlying Payment record this transaction corresponds to.",
    )

    # --- Snapshotted classification (do not rely on unit.classification for history) ---
    unit_classification = models.CharField(
        max_length=15,
        choices=UnitClassification.choices,
        help_text="Snapshotted from unit.classification at transaction creation time.",
    )

    # --- Financial fields (stored, never recalculated on read) ---
    base_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Rent amount before tax.",
    )
    tax_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="VAT applied (0 for RESIDENTIAL, 16 % for BUSINESS).",
    )
    total_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="base_amount + tax_amount. Stored at write time.",
    )

    # --- Payment metadata ---
    payment_mode = models.CharField(
        max_length=10,
        choices=PaymentMode.choices,
    )
    reference_code = models.CharField(
        max_length=100,
        blank=True,
        help_text="External reference stored exactly as received (M-Pesa TransID, bank ref…).",
    )

    # --- Audit ---
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "payments_transaction"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["transaction_id"]),
            models.Index(fields=["tenant", "-created_at"]),
            models.Index(fields=["unit_classification"]),
        ]

    def __str__(self) -> str:
        return (
            f"{self.transaction_id} | {self.tenant} | "
            f"KES {self.total_amount} ({self.unit_classification})"
        )


# ---------------------------------------------------------------------------
# Notifications (unchanged)
# ---------------------------------------------------------------------------

class NotificationChannel(models.TextChoices):
    SMS = "sms", "SMS"
    EMAIL = "email", "Email"
    BOTH = "both", "SMS + Email"


class NotificationStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    SENT = "sent", "Sent"
    FAILED = "failed", "Failed"


class TenantNotification(models.Model):
    """A message sent (or attempted) to a tenant by the admin."""

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.PROTECT,
        related_name="notifications_received",
    )
    channel = models.CharField(
        max_length=10,
        choices=NotificationChannel.choices,
        default=NotificationChannel.SMS,
    )
    subject = models.CharField(max_length=200, blank=True)
    body = models.TextField()

    status = models.CharField(
        max_length=10,
        choices=NotificationStatus.choices,
        default=NotificationStatus.PENDING,
    )
    sent_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True)

    template_key = models.CharField(
        max_length=50,
        blank=True,
        help_text="Identifier of the template used (blank if custom).",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notifications_sent",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "payments_notification"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.get_channel_display()} → {self.tenant} ({self.status})"
