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


class DepositAdjustmentError(Exception):
    """An edited deposit that cannot be put on the books as asked."""


@transaction.atomic
def adjust_deposit_held(tenant: Tenant, new_amount, *, actor=None, on: date | None = None):
    """Bring the booked deposit to ``new_amount`` after the director edits it.

    Editing ``deposit_paid`` used to change the card and nothing else: the
    statement and 2100 read DEPOSIT payments, so the edit looked lost the
    moment a statement was drawn. The difference is now booked instead.

      * Raised  — a DEPOSIT payment for the difference, dated ``on`` (today).
      * Lowered — DEPOSIT payments are voided newest first until the books are
        at or below the new figure, and any remainder of the last one voided is
        re-booked on that payment's own date, source and reference, so the
        statement still shows the deposit when it was actually received.

    A cutover deposit is a bare journal entry with no payment to void, so the
    figure cannot be taken below it here; that needs an accountant's journal.

    Returns the Payments created.
    """
    from apps.accounts import audit
    from apps.payments.models import Payment, PaymentSource, PaymentType
    from apps.payments.services import void_payment

    from .deposits import CENTS, deposit_held_on_books, opening_deposit_on_books

    # Serialise concurrent edits of the same tenant: both would otherwise read
    # the same "before" and book the difference twice.
    Tenant.objects.select_for_update().filter(pk=tenant.pk).first()

    new = Decimal(str(new_amount or 0)).quantize(CENTS)
    before = deposit_held_on_books(tenant)
    created, voided = [], []
    created_by = actor if getattr(actor, "is_authenticated", False) else None

    if new != before:
        held = before
        if new < before:
            opening = opening_deposit_on_books(tenant)
            if new < opening:
                raise DepositAdjustmentError(
                    f"KES {opening:,.2f} of this deposit was brought in at cutover and "
                    f"cannot be reduced from here. Ask the accountant to post a journal."
                )
            deposits = Payment.objects.filter(
                tenant=tenant, payment_type=PaymentType.DEPOSIT, voided_at__isnull=True,
            ).order_by("-payment_date", "-created_at")
            for pay in deposits:
                if held <= new:
                    break
                void_payment(pay, actor=actor, reason=f"Deposit edited to KES {new:,.2f}")
                voided.append(pay)
                held -= pay.amount
                if held < new:
                    created.append(_book_deposit(
                        tenant, new - held, on=pay.payment_date, source=pay.source,
                        reference=pay.reference, created_by=created_by,
                        notes=f"Deposit edited to KES {new:,.2f}; remainder of payment #{pay.pk}.",
                    ))
                    held = new
        if new > held:
            on = on or date.today()
            created.append(_book_deposit(
                tenant, new - held, on=on, source=PaymentSource.CASH, reference="",
                created_by=created_by,
                notes=f"Deposit edited from KES {before:,.2f} to KES {new:,.2f}.",
            ))

        # The ledger signals swallow a posting error (recording a
        # PostingFailure) so a tenant's payment is never lost to a GL hiccup.
        # A deposit edit is not a tenant's payment: if its entries did not reach
        # 1030/2100 the edit must not stand either, or the card and statement
        # would move while the books did not. Raising unwinds the whole edit.
        _assert_posted(created, kind="normal")
        _assert_posted(voided, kind="reversal")

        audit.record(
            actor=actor,
            action="tenant.deposit_adjust",
            object_type="tenant",
            object_id=tenant.pk,
            summary=f"Deposit held for {tenant} changed from KES {before} to KES {new}",
            old_values={"deposit_held": before},
            new_values={"deposit_held": new, "payments": [p.pk for p in created]},
        )

    if tenant.deposit_paid != new:
        tenant.deposit_paid = new
        tenant.save(update_fields=["deposit_paid", "updated_at"])
    return created


def _assert_posted(payments, *, kind):
    from apps.ledger.models import JournalEntry

    ids = [p.pk for p in payments]
    posted = set(
        JournalEntry.objects.filter(source_type="payment", source_id__in=ids, kind=kind)
        .values_list("source_id", flat=True)
    )
    if set(ids) - posted:
        raise DepositAdjustmentError(
            "The deposit change could not be posted to the ledger, so nothing was "
            "saved. Try again, or check Posting Failures."
        )


def _book_deposit(tenant, amount, *, on, source, reference, notes, created_by):
    from apps.payments.models import Payment, PaymentType
    from apps.payments.services import process_payment

    # Numbered by how many deposit rows this tenant already has, voided ones
    # included, so an edit that returns to an earlier figure on the same day is
    # not mistaken for a replay of the first booking.
    ordinal = Payment.objects.filter(tenant=tenant, payment_type=PaymentType.DEPOSIT).count()
    return process_payment(
        tenant=tenant,
        amount=amount,
        payment_date=on,
        period_month=on.month,
        period_year=on.year,
        source=source,
        payment_type=PaymentType.DEPOSIT,
        reference=reference,
        notes=notes,
        idempotency_key=f"DEPOSIT-ADJ-{tenant.pk}-{ordinal}",
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
