"""
Tenant models — updated with deposit refund logic, move-out notice, and KYC.
"""
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.utils import timezone

from apps.buildings.models import Unit


class TenantStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    NOTICE_GIVEN = "notice_given", "Notice Given"
    MOVED_OUT = "moved_out", "Moved Out"
    ARCHIVED = "archived", "Archived"


class KycStatus(models.TextChoices):
    NOT_STARTED = "not_started", "Not Started"
    PENDING = "pending", "Pending Review"
    VERIFIED = "verified", "Verified"
    REJECTED = "rejected", "Rejected"


# KRA PIN: 'A' (individuals) or 'P' (non-individuals), 9 digits, trailing check letter.
kra_pin_validator = RegexValidator(
    regex=r"^[AP]\d{9}[A-Z]$",
    message="KRA PIN must look like 'A007523148T' — a letter, 9 digits, then a letter.",
)


class Tenant(models.Model):
    # Identity
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    id_number = models.CharField(max_length=30, unique=True)
    kra_pin = models.CharField(
        max_length=20, blank=True, validators=[kra_pin_validator],
        help_text="KRA PIN shown on rent statements (e.g. 'A007523148T'). Optional.",
    )
    phone = models.CharField(max_length=20)
    email = models.EmailField(blank=True)
    emergency_contact = models.CharField(max_length=100, blank=True)
    emergency_phone = models.CharField(max_length=20, blank=True)
    care_of = models.CharField(
        max_length=120, blank=True,
        help_text="'c/o' line shown on the rent statement (e.g. 'David Chibeka').",
    )

    # KYC — admin reviews the tenant's ID + KRA PIN + supporting documents.
    kyc_status = models.CharField(
        max_length=15, choices=KycStatus.choices, default=KycStatus.NOT_STARTED, db_index=True,
    )
    kyc_verified_at = models.DateTimeField(null=True, blank=True)
    kyc_verified_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="kyc_verifications",
    )
    kyc_notes = models.TextField(blank=True, help_text="Reviewer notes / rejection reason.")

    # Tenancy
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name="tenants")
    monthly_rent = models.DecimalField(max_digits=10, decimal_places=2)
    deposit_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    # What the landlord actually agreed with this tenant, where that differs
    # from the rule in ``apps.tenants.deposits`` (one month's rent; three for a
    # commercial letting). Some lettings were agreed at an odd figure long
    # before the rule was written down, and holding them against the rule
    # reported a shortfall that nobody owes. Blank means "use the rule" — that
    # is the normal case, and the override is meant to stay rare.
    agreed_deposit = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(0)],
        help_text=(
            "Deposit agreed with this tenant, if it differs from the standard "
            "rule. Leave blank to use one month's rent (three if commercial)."
        ),
    )
    due_day = models.PositiveSmallIntegerField(
        default=5,
        validators=[MinValueValidator(1), MaxValueValidator(31)],
        help_text="Day of the month the rent is due (1-31). Defaults to 5th."
    )


    # Deposit refund: admin sets % to return on move-out
    deposit_refund_percentage = models.DecimalField(
        max_digits=5, decimal_places=2, default=100,
        help_text="Percentage of deposit to refund on move-out (0-100)."
    )
    deposit_refund_amount = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Calculated refund amount at move-out time."
    )

    move_in_date = models.DateField()
    move_out_date = models.DateField(null=True, blank=True)

    # Move-out notice: tenant or admin sets intended departure date
    notice_date = models.DateField(
        null=True, blank=True,
        help_text="Date move-out notice was given."
    )
    intended_move_out_date = models.DateField(
        null=True, blank=True,
        help_text="Tenant's stated intended move-out date."
    )

    status = models.CharField(max_length=15, choices=TenantStatus.choices, default=TenantStatus.ACTIVE, db_index=True)
    move_out_notes = models.TextField(blank=True)
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tenants_tenant"
        # Active tenants first, then by move-in date descending
        ordering = ["-status", "-move_in_date"]

    def __str__(self) -> str:
        return f"{self.first_name} {self.last_name} ({self.unit})"

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    @property
    def is_active(self) -> bool:
        return self.status in (TenantStatus.ACTIVE, TenantStatus.NOTICE_GIVEN)

    # --- KYC ---

    @property
    def kyc_complete(self) -> bool:
        return self.kyc_status == KycStatus.VERIFIED

    @property
    def has_identity_document(self) -> bool:
        return self.documents.filter(
            doc_type__in=[DocumentType.ID_FRONT, DocumentType.PASSPORT]
        ).exists()

    @property
    def kyc_missing_items(self) -> list[str]:
        """What's still needed before this tenant can be marked verified."""
        missing = []
        if not self.kra_pin:
            missing.append("KRA PIN")
        if not self.has_identity_document:
            missing.append("ID or passport copy")
        if not self.documents.filter(doc_type=DocumentType.KRA_PIN_CERTIFICATE).exists():
            missing.append("KRA PIN certificate")
        return missing

    def submit_kyc(self) -> None:
        """Move to PENDING once the minimum identity data is on file."""
        if self.kra_pin and self.has_identity_document and self.kyc_status in (
            KycStatus.NOT_STARTED, KycStatus.REJECTED,
        ):
            self.kyc_status = KycStatus.PENDING
            self.save(update_fields=["kyc_status", "updated_at"])

    def mark_kyc_verified(self, user) -> None:
        self.kyc_status = KycStatus.VERIFIED
        self.kyc_verified_at = timezone.now()
        self.kyc_verified_by = user
        self.save(update_fields=["kyc_status", "kyc_verified_at", "kyc_verified_by", "updated_at"])

    def reject_kyc(self, user, reason: str) -> None:
        self.kyc_status = KycStatus.REJECTED
        self.kyc_verified_at = None
        self.kyc_verified_by = user
        self.kyc_notes = reason
        self.save(update_fields=["kyc_status", "kyc_verified_at", "kyc_verified_by", "kyc_notes", "updated_at"])


class DocumentType(models.TextChoices):
    ID_FRONT = "id_front", "ID Front"
    ID_BACK = "id_back", "ID Back"
    PASSPORT = "passport", "Passport"
    KRA_PIN_CERTIFICATE = "kra_pin_certificate", "KRA PIN Certificate"
    LEASE = "lease", "Lease Agreement"
    OTHER = "other", "Other"


def tenant_document_path(instance: "TenantDocument", filename: str) -> str:
    return f"tenant_docs/{instance.tenant_id}/{filename}"


class TenantDocument(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="documents")
    doc_type = models.CharField(max_length=20, choices=DocumentType.choices, default=DocumentType.OTHER)
    file = models.FileField(upload_to=tenant_document_path)
    original_name = models.CharField(max_length=255)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "tenants_document"
        ordering = ["-uploaded_at"]

    def __str__(self) -> str:
        return f"{self.tenant.full_name} — {self.get_doc_type_display()}"
