"""
Tenant lifecycle operations.

move_in_tenant:  Assign tenant to unit → unit status → OCCUPIED_UNPAID.
move_out_tenant: Record move-out date → unit status → VACANT → tenant archived.
"""
import os
import re
from datetime import date
from decimal import Decimal

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


def record_initial_deposit(
    tenant: Tenant,
    *,
    received_on: date | None = None,
    source: str = "cash",
    reference: str = "",
    created_by=None,
):
    """Book the rent security deposit a new tenant arrived with.

    ``Tenant.deposit_paid`` on its own is only a note of how much is held; it
    moves no money. Registering a letting used to leave it at that, so the
    cash never reached the books: 1030 (Tenant Security Deposit Bank) and 2100
    (Tenant Security Deposits Held) both stayed flat, and a deposit was visible
    on the tenant's card while being absent from the balance sheet. Existing
    tenants only have theirs on the books because the cutover posted it through
    ``post_opening_balances``; a tenant registered afterwards had no equivalent.

    Posting it as a DEPOSIT payment reuses the path the dashboard's own
    "record a payment" screen uses, so the ledger entry, the Transaction row
    and the void/reversal trail are exactly what they would be for a deposit
    keyed in by hand. ``process_payment`` leaves arrears alone for anything
    that is not RENT, so this settles no rent obligation — correct, since a
    deposit is a liability the landlord holds, not income.

    No receipt is sent: the notification tasks are called explicitly by the
    payments views, not by a signal, and a move-in is not the moment to SMS
    somebody a receipt for money they handed over in person.

    Returns the Payment, or None when there is no deposit to book.
    """
    from apps.payments.models import PaymentType
    from apps.payments.services import process_payment

    amount = Decimal(str(tenant.deposit_paid or 0))
    if amount <= 0:
        return None

    received_on = received_on or tenant.move_in_date or date.today()

    return process_payment(
        tenant=tenant,
        amount=amount,
        payment_date=received_on,
        # The deposit belongs to the month it was received, which is the month
        # the tenancy starts. It settles no period — process_payment only
        # touches arrears for RENT — but Payment requires a period, and the
        # move-in month is the one a reader would expect to find it under.
        period_month=received_on.month,
        period_year=received_on.year,
        source=source,
        payment_type=PaymentType.DEPOSIT,
        reference=reference,
        notes="Rent security deposit received at move-in.",
        # A tenant can only be registered once, so this key is unique by
        # construction; it exists so a double-submitted registration that got
        # as far as creating the tenant cannot book the deposit twice.
        idempotency_key=f"DEPOSIT-MOVEIN-{tenant.pk}",
        created_by=created_by,
    )


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
