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
from decimal import Decimal

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
            "rows and sets '<transaction id>#<chunk>' on each. Unique PER TENANT "
            "when non-blank — see the constraint note below."
        ),
    )
    notes = models.TextField(blank=True)

    # --- Void (see services.void_payment) ---
    # Payments are immutable: a mistake is unwound by marking the row void and
    # posting a mirror-image journal entry, never by editing or deleting it.
    # A voided payment is excluded from every balance, arrears and income sum.
    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payments_voided",
    )
    void_reason = models.CharField(max_length=255, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payments_recorded",
        help_text="Who recorded this payment. Null for automated (bank IPN) ingestion.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "payments_payment"
        ordering = ["-payment_date", "-created_at"]
        indexes = [
            models.Index(fields=["tenant", "period_year", "period_month"]),
            models.Index(fields=["period_year", "period_month"]),
            models.Index(fields=["reference"]),
            models.Index(fields=["voided_at"]),
        ]
        constraints = [
            # Scoped to the TENANT on purpose. A global key silently collapsed
            # two different tenants who happened to share a reference — cash
            # receipt books restart at "001", cheque numbers repeat across banks
            # — and the second tenant's money was never recorded. Bank
            # transaction ids are globally unique anyway, so scoping costs the
            # webhook path nothing and makes the manual path safe.
            models.UniqueConstraint(
                fields=["tenant", "idempotency_key"],
                condition=~models.Q(idempotency_key=""),
                name="unique_payment_idempotency_key_per_tenant",
            ),
        ]

    def __str__(self) -> str:
        return f"KES {self.amount} — {self.tenant} ({self.period_month}/{self.period_year})"

    @property
    def is_void(self) -> bool:
        return self.voided_at is not None


class Arrears(models.Model):
    """Outstanding balance for a tenant in a given period."""

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.PROTECT,
        related_name="arrears",
    )
    period_month = models.PositiveSmallIntegerField()
    period_year = models.PositiveIntegerField()
    expected_rent = models.DecimalField(
        max_digits=10, decimal_places=2,
        help_text="Rent billed for the period, VAT-EXCLUSIVE (the base rent).",
    )
    expected_vat = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text=(
            "16% VAT owed on top of expected_rent for BUSINESS units; 0 for "
            "residential. Commercial tenants pay rent+VAT as one figure, so the "
            "obligation a payment is measured against is expected_rent + "
            "expected_vat — comparing gross cash to base rent cleared commercial "
            "arrears 16% early and spilled the VAT into the next period as rent."
        ),
    )
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    balance = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="expected_total - (amount_paid + waived_amount + credit_applied). Positive = owed.",
    )
    is_cleared = models.BooleanField(default=False)
    waived_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    waive_notes = models.TextField(blank=True)
    credit_applied = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text=(
            "Overpayment carried forward from an earlier period and applied to "
            "this one. Without it a tenant who prepaid had the excess floored to "
            "zero and was billed — and dunned — in full the following month."
        ),
    )

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
            models.CheckConstraint(
                condition=models.Q(balance__gte=0),
                name="arrears_balance_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(period_month__gte=1) & models.Q(period_month__lte=12),
                name="arrears_period_month_valid",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "is_cleared"]),
        ]

    def __str__(self) -> str:
        status = "cleared" if self.is_cleared else f"KES {self.balance} owed"
        return f"{self.tenant} — {self.period_month}/{self.period_year} ({status})"

    @property
    def expected_total(self) -> "models.DecimalField":
        """The full obligation for the period — rent plus any VAT on it."""
        return (self.expected_rent or 0) + (self.expected_vat or 0)

    @property
    def covered(self):
        """Everything that discharges the obligation: cash, waivers, credit."""
        return (self.amount_paid or 0) + (self.waived_amount or 0) + (self.credit_applied or 0)


# ---------------------------------------------------------------------------
# UtilityCharge — water / electricity / other monthly usage billed to a tenant
# ---------------------------------------------------------------------------

class UtilityCharge(models.Model):
    """
    A non-rent charge that appears on the tenant's statement ledger.

    Designed to render lines like:
        "Water Usage Feb. '26"                            3,700
        "Water usage - Mar. '26 (7 units @ KES 150)"      1,050

    Meter readings are stored on the charge but deliberately kept off the
    statement: the tenant-facing document shows the consumption and what it
    cost, not the raw dial figures behind it.
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

    def rate_per_unit(self):
        """The tariff this charge was actually billed at, or None.

        Derived from the stored amount and units rather than read off the
        building, so a charge raised when water cost 150 keeps saying 150 after
        the tariff moves to 200. The statement is a record of what was charged,
        not a re-pricing of it. Only an exact division is reported — a figure
        that does not divide cleanly is not a per-unit rate and claiming one
        would invite a tenant to check the arithmetic and find it wrong.
        """
        if not self.units or self.amount is None:
            return None
        rate = (Decimal(self.amount) / Decimal(self.units)).quantize(Decimal("0.01"))
        if rate * Decimal(self.units) != Decimal(self.amount):
            return None
        return rate

    def description(self) -> str:
        """Render the description used in the rent statement ledger."""
        try:
            # Full month and year, matching every other month named on the
            # statement. "Water usage May. '26" was the only abbreviation left
            # on the page once the rent lines and dates were spelled out.
            period_short = _dt.date(self.period_year, self.period_month, 1).strftime("%B %Y")
        except ValueError:
            period_short = f"{self.period_month}/{self.period_year}"
        first = f"{self.label} {period_short}"
        if self.units is not None:
            units_int = int(self.units) if self.units == self.units.to_integral_value() else self.units
            rate = self.rate_per_unit()
            if rate is None:
                first += f" ({units_int} Units)"
            else:
                rate_text = f"{int(rate):,}" if rate == rate.to_integral_value() else f"{rate:,.2f}"
                first += f" ({units_int} Units @ KES {rate_text})"
        return first


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


# ---------------------------------------------------------------------------
# Tenant credits and refunds
# ---------------------------------------------------------------------------
#
# A credit on a tenant's account is a numbered document, never a typed-in
# balance. The balance stays derived: charges less receipts less credits plus
# refunds. Three records do the work:
#
#   TenantCredit        the credit itself. Its REASON decides which account is
#                       debited when it is issued (income for a credit note, an
#                       expense for a cost the tenant bore, equity for a credit
#                       owed from before the books began); the tenant side is
#                       always 1040.
#   CreditApplication   a credit settling part of a month's rent. The charge is
#                       not edited; the application sits beside it and is what
#                       `Arrears.credit_applied` totals up.
#   Refund / RefundLine money actually sent back to the tenant, and the credit
#                       it was drawn from.
#
# Overpayments are not TenantCredit rows yet: they are still the surplus the
# arrears subledger carries (see services.available_credit). A refund can draw
# on that surplus too, through a RefundLine with no credit.
#
# Nothing here is edited or deleted once it takes effect. A mistake is voided
# with a reason, which posts a mirror-image journal entry dated the day of the
# void.


class DocumentSequence(models.Model):
    """Gap-free running number per document series (CN, CR, RF)."""

    name = models.CharField(max_length=20, unique=True)
    last = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "payments_document_sequence"

    def __str__(self) -> str:
        return f"{self.name}: {self.last}"


class CreditType(models.TextChoices):
    #: Reduces a charge that was billed; carries the VAT of that charge.
    CREDIT_NOTE = "credit_note", "Credit Note"
    #: Any other entitlement — does not change what a charge was worth.
    ACCOUNT_CREDIT = "account_credit", "Account Credit"


class CreditReason(models.TextChoices):
    BILLING_CORRECTION = "billing_correction", "We charged too much"
    RENT_CONCESSION = "rent_concession", "Rent discount or concession"
    TENANT_PAID_COST = "tenant_paid_cost", "Tenant paid for a repair or cost that was ours"
    OPENING_CREDIT = "opening_credit", "Credit owed from before the system"


#: The document a reason produces. Kept beside the reasons so the service and
#: the API cannot disagree about it.
CREDIT_TYPE_FOR_REASON = {
    CreditReason.BILLING_CORRECTION: CreditType.CREDIT_NOTE,
    CreditReason.RENT_CONCESSION: CreditType.CREDIT_NOTE,
    CreditReason.TENANT_PAID_COST: CreditType.ACCOUNT_CREDIT,
    CreditReason.OPENING_CREDIT: CreditType.ACCOUNT_CREDIT,
}


class CreditStatus(models.TextChoices):
    # Owner-only today, so a credit is issued the moment it is confirmed. A
    # pending-approval state slots in ahead of ISSUED once there is a second
    # user; nothing downstream reads anything but ISSUED/VOID.
    ISSUED = "issued", "Issued"
    VOID = "void", "Void"


def credit_evidence_path(instance: "TenantCredit", filename: str) -> str:
    return f"credit_evidence/{instance.tenant_id}/{filename}"


class TenantCredit(models.Model):
    """A numbered credit on a tenant's account."""

    number = models.CharField(max_length=20, unique=True, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="credits")
    credit_type = models.CharField(max_length=20, choices=CreditType.choices)
    reason = models.CharField(max_length=30, choices=CreditReason.choices)
    credit_date = models.DateField(help_text="Date the credit takes effect and posts to the ledger.")

    # Figures, stored at issue time and never recalculated on read.
    net_amount = models.DecimalField(
        max_digits=10, decimal_places=2,
        help_text="The credit before VAT — what the charge is reduced by.",
    )
    vat_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text="VAT credited back. Only when the corrected charge carried VAT.",
    )
    amount = models.DecimalField(
        max_digits=10, decimal_places=2,
        help_text="net_amount + vat_amount — what the tenant's balance goes down by.",
    )

    # What the credit corrects (credit notes) or what it paid for.
    arrears = models.ForeignKey(
        Arrears, on_delete=models.PROTECT, null=True, blank=True,
        related_name="credit_notes",
        help_text="The month's rent this credit note corrects.",
    )
    utility_charge = models.ForeignKey(
        UtilityCharge, on_delete=models.PROTECT, null=True, blank=True,
        related_name="credit_notes",
        help_text="The water/utility charge this credit note corrects.",
    )
    expense_category = models.ForeignKey(
        "expenses.ExpenseCategory", on_delete=models.PROTECT, null=True, blank=True,
        related_name="tenant_credits",
        help_text="For a cost the tenant bore on the landlord's behalf.",
    )

    description = models.CharField(
        max_length=200,
        help_text="Printed on the tenant's statement — written for the tenant.",
    )
    internal_notes = models.TextField(blank=True, help_text="Never shown to the tenant.")
    reference = models.CharField(max_length=100, blank=True)
    evidence = models.FileField(upload_to=credit_evidence_path, blank=True)
    evidence_name = models.CharField(max_length=255, blank=True)

    on_hold = models.BooleanField(
        default=False,
        help_text="Held credit is not applied to invoices automatically.",
    )

    # Running totals of what the credit has been used for, kept on the row so
    # the database itself refuses a credit being used twice (see constraints).
    amount_applied = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    amount_refunded = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text="Refunded, or set aside for a refund still to be sent.",
    )

    status = models.CharField(max_length=10, choices=CreditStatus.choices, default=CreditStatus.ISSUED)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="credits_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    # Separate from created_by so a maker-checker step can be added later
    # without changing the record. Today the owner is both.
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="credits_approved",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    approval_mode = models.CharField(
        max_length=30, default="owner_self",
        help_text="How it was approved. 'owner_self' = sole owner, no second approver.",
    )

    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="credits_voided",
    )
    void_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "payments_tenant_credit"
        ordering = ["-credit_date", "-id"]
        indexes = [
            models.Index(fields=["tenant", "status"]),
        ]
        constraints = [
            models.CheckConstraint(condition=models.Q(net_amount__gt=0), name="credit_net_positive"),
            models.CheckConstraint(condition=models.Q(vat_amount__gte=0), name="credit_vat_non_negative"),
            models.CheckConstraint(
                condition=models.Q(amount=models.F("net_amount") + models.F("vat_amount")),
                name="credit_amount_is_net_plus_vat",
            ),
            models.CheckConstraint(
                condition=models.Q(amount_applied__gte=0) & models.Q(amount_refunded__gte=0),
                name="credit_usage_non_negative",
            ),
            # The database-level guard against using the same credit twice.
            models.CheckConstraint(
                condition=models.Q(
                    amount__gte=models.F("amount_applied") + models.F("amount_refunded")
                ),
                name="credit_not_overused",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.number} — KES {self.amount} ({self.tenant})"

    @property
    def is_void(self) -> bool:
        return self.status == CreditStatus.VOID

    @property
    def remaining(self) -> Decimal:
        """What is still available to apply or refund."""
        if self.is_void:
            return Decimal("0.00")
        return self.amount - self.amount_applied - self.amount_refunded


class CreditApplicationOrigin(models.TextChoices):
    ON_ISSUE = "on_issue", "Applied when the credit was added"
    BILLING = "billing", "Applied by the monthly billing run"
    OWNER = "owner", "Applied by the owner"


class CreditApplication(models.Model):
    """Part of a credit settling part of one month's rent."""

    credit = models.ForeignKey(TenantCredit, on_delete=models.PROTECT, related_name="applications")
    arrears = models.ForeignKey(Arrears, on_delete=models.PROTECT, related_name="credit_applications")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    applied_on = models.DateField()
    origin = models.CharField(max_length=10, choices=CreditApplicationOrigin.choices)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    reversed_at = models.DateTimeField(null=True, blank=True)
    reversed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+",
    )
    reverse_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "payments_credit_application"
        ordering = ["applied_on", "id"]
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="credit_application_positive"),
        ]

    def __str__(self) -> str:
        return f"{self.credit.number} → {self.arrears} KES {self.amount}"

    @property
    def is_active(self) -> bool:
        return self.reversed_at is None


class RefundStatus(models.TextChoices):
    SCHEDULED = "scheduled", "Refund to send"
    SENT = "sent", "Refunded"
    CANCELLED = "cancelled", "Cancelled"
    VOID = "void", "Void"


#: Refund states that hold on to the credit they were drawn from.
REFUND_ACTIVE_STATUSES = (RefundStatus.SCHEDULED, RefundStatus.SENT)


class Refund(models.Model):
    """Money sent back to a tenant out of the credit on their account."""

    number = models.CharField(max_length=20, unique=True, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="refunds")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    method = models.CharField(max_length=10, choices=PaymentSource.choices)
    paid_to = models.CharField(
        max_length=100, blank=True,
        help_text="Phone number or bank account the money went to.",
    )
    reference = models.CharField(
        max_length=100, blank=True,
        help_text="M-Pesa / bank reference of the outgoing payment.",
    )
    notes = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=10, choices=RefundStatus.choices)
    sent_on = models.DateField(null=True, blank=True, help_text="Date the money actually left.")
    # Snapshotted so a later change to the unit cannot re-price the refund of
    # an overpayment, which reverses VAT on a commercial letting.
    unit_classification = models.CharField(max_length=15, choices=UnitClassification.choices)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="refunds_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="refunds_approved",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    approval_mode = models.CharField(max_length=30, default="owner_self")
    sent_recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+",
    )
    sent_recorded_at = models.DateTimeField(null=True, blank=True)

    closed_at = models.DateTimeField(null=True, blank=True, help_text="When it was cancelled or voided.")
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+",
    )
    close_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "payments_refund"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["tenant", "status"]),
        ]
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="refund_amount_positive"),
            models.CheckConstraint(
                condition=~models.Q(status="sent") | models.Q(sent_on__isnull=False),
                name="refund_sent_has_date",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.number} — KES {self.amount} to {self.tenant} ({self.status})"


class RefundLine(models.Model):
    """Where a refund's money came from: a credit, or overpaid rent (credit=None)."""

    refund = models.ForeignKey(Refund, on_delete=models.PROTECT, related_name="lines")
    credit = models.ForeignKey(
        TenantCredit, on_delete=models.PROTECT, null=True, blank=True,
        related_name="refund_lines",
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        db_table = "payments_refund_line"
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="refund_line_positive"),
        ]

    def __str__(self) -> str:
        source = self.credit.number if self.credit_id else "overpayment"
        return f"{self.refund.number} ← {source} KES {self.amount}"
