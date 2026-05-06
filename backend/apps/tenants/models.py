"""
Tenant models — updated with deposit refund logic and move-out notice.
"""
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.buildings.models import Unit


class TenantStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    NOTICE_GIVEN = "notice_given", "Notice Given"
    MOVED_OUT = "moved_out", "Moved Out"
    ARCHIVED = "archived", "Archived"


class Tenant(models.Model):
    # Identity
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    id_number = models.CharField(max_length=30, unique=True)
    phone = models.CharField(max_length=20)
    email = models.EmailField(blank=True)
    emergency_contact = models.CharField(max_length=100, blank=True)
    emergency_phone = models.CharField(max_length=20, blank=True)

    # Tenancy
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name="tenants")
    monthly_rent = models.DecimalField(max_digits=10, decimal_places=2)
    deposit_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0)
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


class DocumentType(models.TextChoices):
    ID_FRONT = "id_front", "ID Front"
    ID_BACK = "id_back", "ID Back"
    PASSPORT = "passport", "Passport"
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
