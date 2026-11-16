"""Voiding an expense or an income entry.

Neither is deleted from the dashboard any more. A void keeps the row, records
who voided it, when and why, and posts the mirror-image reversal to the
ledger, so the books still show the entry was made and then undone. Totals
leave voided rows out.
"""
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.accounts import audit

from .models import Expense, ManualIncome


def _reverse(entry) -> None:
    from apps.ledger import posting
    from apps.ledger.signals import _safe_post

    if isinstance(entry, Expense):
        if not (entry.category_id and entry.category.account_id):
            return  # never posted, nothing to reverse
        _safe_post(
            source_type="expense", source_id=entry.pk, kind="reversal", operation="reverse",
            fn=lambda: posting.reverse_expense(entry),
        )
    else:
        _safe_post(
            source_type="manual_income", source_id=entry.pk, kind="reversal", operation="reverse",
            fn=lambda: posting.reverse_manual_income(entry),
        )


def void_entry(entry: Expense | ManualIncome, *, user, reason: str) -> Expense | ManualIncome:
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError({"reason": "Say why it is being voided."})

    model = type(entry)
    with transaction.atomic():
        entry = model.objects.select_for_update().get(pk=entry.pk)
        if entry.is_void:
            raise ValidationError({"detail": "This entry is already void."})
        if isinstance(entry, Expense):
            from apps.buildings.models import MaintenanceRequest

            request = MaintenanceRequest.objects.filter(expense=entry).first()
            if request is not None:
                raise ValidationError({"detail": (
                    f"This cost comes from maintenance request #{request.pk}. "
                    "Change or remove the cost there instead."
                )})

        entry.voided_at = timezone.now()
        entry.voided_by = user
        entry.void_reason = reason[:255]
        # The ledger's save handler skips voided rows, so this does not re-post.
        entry.save(update_fields=["voided_at", "voided_by", "void_reason", "updated_at"])
        _reverse(entry)

        kind = "expense" if isinstance(entry, Expense) else "manual_income"
        noun = "expense" if kind == "expense" else "income"
        audit.record(
            action=f"{kind}.void",
            object_type=kind,
            object_id=entry.pk,
            object_label=entry.description[:150],
            summary=f"Voided {noun} {entry.description[:80]} (KES {entry.amount}): {reason}"[:255],
            actor=user,
            new_values={"void_reason": reason},
            is_financial=True,
        )
    return entry
