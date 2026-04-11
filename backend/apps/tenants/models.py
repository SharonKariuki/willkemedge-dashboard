"""
Tenant models.

A Tenant occupies a Unit. The lifecycle runs:
  registered (move_in_date set) → active → moved_out (move_out_date set) → archived.

TenantDocument stores file references (ID scans, lease agreements) associated
with a Tenant. Files themselves live in S3 (or local media in dev).
"""
from django.db import models

from apps.buildings.models import Unit


class TenantStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    MOVED_OUT = "moved_out", "Moved Out"
    ARCHIVED = "archived", "Archived"


class Tenant(models.Model):
    """A person renting a unit."""

    # Identity
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    id_number = models.CharField(
        max_length=30,
        unique=True,
        help_text="National ID or passport number.",
    )
    phone = models.CharField(max_length=20)
    email = models.EmailField(blank=True)
    emergency_contact = models.CharField(max_length=100, blank=True)
    emergency_phone = models.CharField(max_length=20, blank=True)

    # Tenancy
    unit = models.ForeignKey(
        Unit,
        on_delete=models.PROTECT,
        related_name="tenants",
    )
    monthly_rent = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Agreed rent in KES. Defaults to unit rent at move-in, but can differ.",
    )
    deposit_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    move_in_date = models.DateField()
    move_out_date = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=15,
        choices=TenantStatus.choices,
        default=TenantStatus.ACTIVE,
        db_index=True,
    )
    move_out_notes = models.TextField(
        blank=True,
        help_text="Notes recorded at move-out (condition, damages, deposit return).",
    )
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tenants_tenant"
        ordering = ["-move_in_date"]

    def __str__(self) -> str:
        return f"{self.first_name} {self.last_name} ({self.unit})"

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    @property
    def is_active(self) -> bool:
        return self.status == TenantStatus.ACTIVE


class DocumentType(models.TextChoices):
    ID_FRONT = "id_front", "ID Front"
    ID_BACK = "id_back", "ID Back"
    PASSPORT = "passport", "Passport"
    LEASE = "lease", "Lease Agreement"
    OTHER = "other", "Other"


def tenant_document_path(instance: "TenantDocument", filename: str) -> str:
    """Upload path: tenant_docs/<tenant_id>/<filename>."""
    return f"tenant_docs/{instance.tenant_id}/{filename}"


class TenantDocument(models.Model):
    """A file (ID scan, lease, etc.) attached to a tenant."""

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="documents",
    )
    doc_type = models.CharField(
        max_length=20,
        choices=DocumentType.choices,
        default=DocumentType.OTHER,
    )
    file = models.FileField(upload_to=tenant_document_path)
    original_name = models.CharField(max_length=255)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "tenants_document"
        ordering = ["-uploaded_at"]

    def __str__(self) -> str:
        return f"{self.tenant.full_name} — {self.get_doc_type_display()}"
