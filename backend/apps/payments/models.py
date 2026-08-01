"""
Payment and Arrears models.

Payments are immutable financial records. Once created, they are never
soft-deleted or modified. Only the admin can void a payment by creating
a reverse entry.

Arrears track outstanding balances per tenant per month.

Transaction is the auditable financial record that stores every tax-derived
value at write time so reads never recalculate derived figures.
"""
import datetime as _dt

from django.conf import settings
from django.db import models

from apps.buildings.models import UnitClassification
from apps.tenants.models import Tenant


class PaymentSource(models.TextChoices):
    MPESA = "mpesa", "M-Pesa"
    BANK = "bank", "Bank Transfer"
    CASH = "cash", "Cash"
    CHEQUE = "cheque", "Cheque"


class PaymentType(models.TextChoices):
    """How the money is booked in the chart of accounts."""
    RENT = "rent", "Rental Income (4110/4120)"
    LATE_FEE = "late_fee", "Late Fees (4200)"
    DEPOSIT = "deposit", "Security Deposit (2100)"
    OTHER = "other", "Other Income"


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
    payment_type = models.CharField(
        max_length=10,
        choices=PaymentType.choices,
        default=PaymentType.RENT,
        help_text="Used to split income into 4110/4120 (rent), 4200 (late fees), or 2100 (deposit liability).",
    )
    reference = models.CharField(
        max_length=100,
        blank=True,
        help_text="M-Pesa TransID, bank ref, or receipt number.",
    )
    idempotency_key = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text=(
            "Natural-key guard against double-booking a single payment. Single-"
            "payment ingestion (the manual create/mock paths) sets the bare "
            "reference; FIFO allocation splits one credit into several Payment "
            "rows and sets '<transaction id>#<chunk>' on each. Unique when "
            "non-blank."
        ),
    )
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "payments_payment"
        ordering = ["-payment_date", "-created_at"]
        indexes = [
            models.Index(fields=["tenant", "period_year", "period_month"]),
            models.Index(fields=["period_year", "period_month"]),
            models.Index(fields=["reference"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["idempotency_key"],
                condition=~models.Q(idempotency_key=""),
                name="unique_payment_idempotency_key",
            ),
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
# UtilityCharge — water / electricity / other monthly usage billed to a tenant
# ---------------------------------------------------------------------------

class UtilityCharge(models.Model):
    """
    A non-rent charge that appears on the tenant's statement ledger.

    Designed to render lines like:
        "Water Usage Feb. '26"                            3,700
        "Water usage - Mar. '26 (7 units)
         Opening Reading: 1449
         Closing Reading: 1456"                           1,050
    """

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.PROTECT,
        related_name="utility_charges",
    )
    posting_date = models.DateField(help_text="Date this charge posts to the ledger.")
    period_month = models.PositiveSmallIntegerField(help_text="Usage month (1-12).")
    period_year = models.PositiveIntegerField()
    label = models.CharField(
        max_length=60,
        default="Water Usage",
        help_text="Charge label, e.g. 'Water Usage', 'Electricity'.",
    )
    units = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Usage in units (m³, kWh, …). Optional; shown as '(7 units)' if present.",
    )
    opening_reading = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
    )
    closing_reading = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "payments_utility_charge"
        ordering = ["-posting_date", "-id"]
        indexes = [
            models.Index(fields=["tenant", "period_year", "period_month"]),
        ]

    def __str__(self) -> str:
        return f"{self.label} {self.period_month}/{self.period_year} — KES {self.amount}"

    def description(self) -> str:
        """Render the multi-line description used in the rent statement ledger."""
        try:
            period_short = _dt.date(self.period_year, self.period_month, 1).strftime("%b. '%y")
        except ValueError:
            period_short = f"{self.period_month}/{self.period_year}"
        first = f"{self.label} {period_short}"
        if self.units is not None:
            units_int = int(self.units) if self.units == self.units.to_integral_value() else self.units
            first += f" ({units_int} Units)"
        extra = []
        if self.opening_reading is not None:
            extra.append(f"Opening Reading: {int(self.opening_reading) if self.opening_reading == self.opening_reading.to_integral_value() else self.opening_reading}")
        if self.closing_reading is not None:
            extra.append(f"Closing Reading: {int(self.closing_reading) if self.closing_reading == self.closing_reading.to_integral_value() else self.closing_reading}")
        return "\n".join([first, *extra])


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
# Co-op Bank IPN (Instant Payment Notification) event log
# ---------------------------------------------------------------------------

class CoopIpnStatus(models.TextChoices):
    """Outcome of processing a single IPN event."""
    RECORDED = "recorded", "Recorded"          # matched a tenant; Payment created
    UNMATCHED = "unmatched", "Unmatched"        # credit we couldn't tie to a tenant
    DUPLICATE = "duplicate", "Duplicate"        # TransactionId already seen
    IGNORED = "ignored", "Ignored (non-credit)" # DEBIT/other event, not a reversal
    REVERSAL_PENDING = "reversal_pending", "Reversal — awaiting authorization"
    REVERSAL_APPLIED = "reversal_applied", "Reversal applied"
    ERROR = "error", "Error"                    # could not parse / process


class CoopIpnEvent(models.Model):
    """
    A single Instant Payment Notification received from Co-operative Bank.

    Every inbound IPN POST is persisted here verbatim BEFORE any matching is
    attempted. This gives us three things at once:

      1. Idempotency — `transaction_id` (Co-op's `TransactionId`) is unique, so a
         re-delivered event is detected and skipped.
      2. An unmatched-payments review queue — credits we cannot tie to a tenant
         land here with status=UNMATCHED for an admin to reconcile by hand.
      3. A raw audit trail — the full payload is kept so reconciliation can be
         replayed/refined later (and so a parser change can re-process history).

    Records here are an append-only log; they are never mutated except to link
    the resulting Payment and set the final status during initial processing.
    """

    transaction_id = models.CharField(
        max_length=100,
        unique=True,
        help_text="Co-op `TransactionId` — the unique reference for this event.",
    )
    payment_ref = models.CharField(
        max_length=100,
        blank=True,
        help_text="Co-op `PaymentRef` — the unique reference for the payment.",
    )
    account_number = models.CharField(
        max_length=40,
        blank=True,
        help_text="`AcctNo` the credit landed in (the institution account).",
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    event_type = models.CharField(
        max_length=20,
        blank=True,
        help_text="`EventType` from the bank, e.g. CREDIT / DEBIT.",
    )
    channel = models.CharField(
        max_length=10,
        choices=PaymentSource.choices,
        blank=True,
        help_text="Inferred inflow channel (mpesa via Paybill, direct bank, …).",
    )
    narration = models.TextField(
        blank=True,
        help_text="Raw narration string the bill ref / payer details were parsed from.",
    )
    raw_payload = models.JSONField(
        help_text="The full IPN payload exactly as received.",
    )
    status = models.CharField(
        max_length=20,
        choices=CoopIpnStatus.choices,
        default=CoopIpnStatus.ERROR,
    )
    detail = models.CharField(
        max_length=255,
        blank=True,
        help_text="Human-readable note on the outcome (why unmatched, error text, …).",
    )
    payment = models.ForeignKey(
        Payment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="coop_ipn_events",
        help_text="The Payment created from this event, if any.",
    )
    received_at = models.DateTimeField(auto_now_add=True)
    # Maker-checker on REVERSAL_PENDING → REVERSAL_APPLIED. Set when (and only
    # when) the authorising director clicks "Authorize reversal" in admin.
    authorized_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="Director who authorised this reversal (REVERSAL_PENDING → APPLIED).",
    )
    authorized_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "payments_coop_ipn_event"
        ordering = ["-received_at"]
        indexes = [
            models.Index(fields=["transaction_id"]),
            models.Index(fields=["status", "-received_at"]),
        ]

    def __str__(self) -> str:
        return f"IPN {self.transaction_id} — KES {self.amount} ({self.status})"


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
    # Idempotency marker for automated sends (e.g. one rent reminder per tenant
    # per period). Blank for ad-hoc admin messages. The scheduler skips a send
    # when a row with the same dedupe_key already exists, so re-running the
    # daily job never double-sends.
    dedupe_key = models.CharField(max_length=120, blank=True, db_index=True)
    # Africa's Talking delivery receipt: the provider's message id + the raw
    # send response, persisted so a delivery can be audited later.
    provider_message_id = models.CharField(max_length=120, blank=True)
    provider_response = models.TextField(blank=True)
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
