"""
Tenant lifecycle operations.

move_in_tenant:  Assign tenant to unit → unit status → OCCUPIED_UNPAID.
move_out_tenant: Record move-out date → unit status → VACANT → tenant archived.
"""
import os
import re
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
# Extension allowlist — defence in depth alongside the content-type check,
# since the browser-supplied MIME type cannot be trusted.
ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".webp"}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB


class FileValidationError(Exception):
    pass


def _sniff_content_type(head: bytes) -> str | None:
    """Return the real MIME type from an uploaded file's leading bytes.

    Both the browser-supplied content-type and the filename extension are
    attacker-controlled, so a malicious payload (e.g. an HTML/SVG-with-script
    or an executable) can wear a ``.png``/``image/png`` disguise. Matching the
    actual magic bytes against our allowlist closes that gap without pulling in
    libmagic — the four accepted formats have stable, well-known signatures.
    """
    if head.startswith(b"%PDF-"):
        return "application/pdf"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    # WebP is a RIFF container: "RIFF" <4-byte size> "WEBP".
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None


def sanitize_filename(filename: str) -> str:
    """Strip path components and unsafe characters from an uploaded filename.

    Rejects nothing on its own — always returns a safe basename. Path
    separators and traversal sequences are removed so the value can never
    escape its intended directory or be interpreted as a path.
    """
    # Take the basename only — defeats "../../etc/passwd" and "C:\foo\bar".
    name = os.path.basename(str(filename or "").replace("\\", "/"))
    # Collapse anything that isn't a safe filename character.
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    # Strip leading dots/dashes that could hide the name or form options.
    name = name.lstrip(".-")
    return name or "upload"


def validate_upload(file) -> str:
    """Validate uploaded file type, extension, and size.

    Returns the sanitized filename so callers can store it safely.
    Raises FileValidationError on any violation.
    """
    if file.content_type not in ALLOWED_FILE_TYPES:
        raise FileValidationError(
            f"File type '{file.content_type}' not allowed. "
            f"Accepted: PDF, JPEG, PNG, WebP."
        )

    safe_name = sanitize_filename(file.name)
    ext = os.path.splitext(safe_name)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise FileValidationError(
            f"File extension '{ext or '(none)'}' not allowed. "
            f"Accepted: PDF, JPEG, PNG, WebP."
        )

    if file.size > MAX_FILE_SIZE:
        raise FileValidationError(
            f"File too large ({file.size / 1024 / 1024:.1f} MB). Max: 5 MB."
        )

    # Magic-byte check: confirm the real content matches an allowed format,
    # regardless of the declared type/extension above. Read the header, then
    # rewind so the subsequent save writes the whole file.
    head = file.read(16)
    file.seek(0)
    real_type = _sniff_content_type(head)
    if real_type not in ALLOWED_FILE_TYPES:
        raise FileValidationError(
            "File contents do not match an accepted format. "
            "Accepted: PDF, JPEG, PNG, WebP."
        )

    return safe_name


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
