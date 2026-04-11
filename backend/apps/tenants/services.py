"""
Tenant lifecycle operations.

move_in_tenant:  Assign tenant to unit → unit status → OCCUPIED_UNPAID.
move_out_tenant: Record move-out date → unit status → VACANT → tenant archived.
"""
from datetime import date

from django.db import transaction

from apps.buildings.services import move_in as unit_move_in
from apps.buildings.services import move_out as unit_move_out

from .models import Tenant, TenantStatus

ALLOWED_FILE_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/webp",
}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB


class FileValidationError(Exception):
    pass


def validate_upload(file) -> None:
    """Validate uploaded file type and size."""
    if file.content_type not in ALLOWED_FILE_TYPES:
        raise FileValidationError(
            f"File type '{file.content_type}' not allowed. "
            f"Accepted: PDF, JPEG, PNG, WebP."
        )
    if file.size > MAX_FILE_SIZE:
        raise FileValidationError(
            f"File too large ({file.size / 1024 / 1024:.1f} MB). Max: 5 MB."
        )


@transaction.atomic
def move_in_tenant(tenant: Tenant) -> Tenant:
    """
    Activate a tenant and flip their unit to OCCUPIED_UNPAID.
    Called when tenant is first created (status already ACTIVE by default).
    """
    unit_move_in(tenant.unit)
    return tenant


@transaction.atomic
def move_out_tenant(
    tenant: Tenant,
    move_out_date: date | None = None,
    notes: str = "",
) -> Tenant:
    """
    Process a tenant move-out:
    1. Set move_out_date (defaults to today)
    2. Record move_out_notes
    3. Flip tenant status → MOVED_OUT
    4. Flip unit status → VACANT
    """
    tenant.move_out_date = move_out_date or date.today()
    tenant.move_out_notes = notes
    tenant.status = TenantStatus.MOVED_OUT
    tenant.save(update_fields=["move_out_date", "move_out_notes", "status", "updated_at"])

    unit_move_out(tenant.unit)
    return tenant
