"""
Signals that keep the general ledger in step with the source rows.

We connect to post_save / post_delete on Payment, Expense, ManualIncome and
UtilityCharge:

  * create → post a NORMAL journal entry
  * edit   → RE-POST (replace) the NORMAL entry so a corrected amount reaches
             the books — previously edits never updated the GL, so source
             records and the ledger diverged permanently
  * delete → post a REVERSAL entry (keeping an audit trail)

Posting is best-effort for the source write (we never block recording a tenant
payment because the GL hiccuped), but it is no longer *silent*: any failure is
captured durably in a PostingFailure row so it is visible and replayable via
the ``retry_posting_failures`` management command. A later success resolves the
open failure.
"""
import logging

from django.db.models import F
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.utils import timezone

logger = logging.getLogger(__name__)


def _record_failure(source_type, source_id, kind, operation, exc):
    """Persist (or refresh) an OPEN PostingFailure for a source row."""
    from .models import PostingFailure

    now = timezone.now()
    updated = PostingFailure.objects.filter(
        source_type=source_type, source_id=source_id, kind=kind
    ).update(
        operation=operation,
        error=str(exc)[:2000],
        attempts=F("attempts") + 1,
        resolved=False,
        resolved_at=None,
        updated_at=now,
    )
    if not updated:
        PostingFailure.objects.create(
            source_type=source_type,
            source_id=source_id,
            kind=kind,
            operation=operation,
            error=str(exc)[:2000],
        )


def _resolve_failure(source_type, source_id, kind):
    """Mark any OPEN PostingFailure for a source row as resolved."""
    from .models import PostingFailure

    PostingFailure.objects.filter(
        source_type=source_type, source_id=source_id, kind=kind, resolved=False
    ).update(resolved=True, resolved_at=timezone.now())


def _safe_post(*, source_type, source_id, kind, operation, fn):
    """
    Run a posting callable, capturing failures durably instead of swallowing.

    On success, resolves any open failure for the source. On error, logs and
    records a PostingFailure — without re-raising, so the source row still
    commits and can be replayed later.
    """
    try:
        fn()
    except Exception as exc:
        logger.error(
            "ledger: %s %s#%s (%s) failed: %s",
            operation, source_type, source_id, kind, exc,
        )
        _record_failure(source_type, source_id, kind, operation, exc)
    else:
        _resolve_failure(source_type, source_id, kind)


# ── Payment signals ──────────────────────────────────────────────────────────

@receiver(post_save, sender="payments.Payment")
def on_payment_saved(sender, instance, created, **kwargs):
    """Post on create; re-post (replace) on edit so corrections reach the GL."""
    from apps.ledger.posting import post_payment

    _safe_post(
        source_type="payment", source_id=instance.pk, kind="normal", operation="post",
        fn=lambda: post_payment(instance, replace=not created),
    )


@receiver(post_delete, sender="payments.Payment")
def on_payment_deleted(sender, instance, **kwargs):
    """Create a reversal entry when a Payment is deleted (voided)."""
    from apps.ledger.posting import reverse_payment

    _safe_post(
        source_type="payment", source_id=instance.pk, kind="reversal", operation="reverse",
        fn=lambda: reverse_payment(instance),
    )


# ── Expense signals ──────────────────────────────────────────────────────────

@receiver(post_save, sender="expenses.Expense")
def on_expense_saved(sender, instance, created, **kwargs):
    """Post on create; re-post on edit. Skip if no GL account is mapped."""
    from apps.ledger.posting import post_expense

    if not (instance.category_id and instance.category.account_id):
        logger.warning(
            "ledger: Expense#%s has no GL account — skipping posting.", instance.pk
        )
        return

    _safe_post(
        source_type="expense", source_id=instance.pk, kind="normal", operation="post",
        fn=lambda: post_expense(instance, replace=not created),
    )


@receiver(post_delete, sender="expenses.Expense")
def on_expense_deleted(sender, instance, **kwargs):
    """Create a reversal entry when an Expense is deleted."""
    from apps.ledger.posting import reverse_expense

    if not (instance.category_id and instance.category.account_id):
        return

    _safe_post(
        source_type="expense", source_id=instance.pk, kind="reversal", operation="reverse",
        fn=lambda: reverse_expense(instance),
    )


# ── Manual income signals ────────────────────────────────────────────────────

@receiver(post_save, sender="expenses.ManualIncome")
def on_manual_income_saved(sender, instance, created, **kwargs):
    """Post non-tenant income (e.g. farm produce); re-post on edit."""
    from .posting import post_manual_income

    _safe_post(
        source_type="manual_income", source_id=instance.pk, kind="normal", operation="post",
        fn=lambda: post_manual_income(instance, replace=not created),
    )


@receiver(post_delete, sender="expenses.ManualIncome")
def on_manual_income_deleted(sender, instance, **kwargs):
    """Create a reversal entry when a ManualIncome record is deleted."""
    from .posting import reverse_manual_income

    _safe_post(
        source_type="manual_income", source_id=instance.pk, kind="reversal", operation="reverse",
        fn=lambda: reverse_manual_income(instance),
    )


# ── Utility charge signals ───────────────────────────────────────────────────

@receiver(post_save, sender="payments.UtilityCharge")
def on_utility_charge_saved(sender, instance, created, **kwargs):
    """Post a water/utility charge on create; re-post on a revised reading.

    Meter re-reads use update_or_create, so a corrected reading updates the
    UtilityCharge in place (created=False) — the GL must follow, or recovered
    utility income stays stuck at the first (wrong) figure.
    """
    from .posting import post_utility_charge

    _safe_post(
        source_type="utility_charge", source_id=instance.pk, kind="normal", operation="post",
        fn=lambda: post_utility_charge(instance, replace=not created),
    )
