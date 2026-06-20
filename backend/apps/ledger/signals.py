"""
Signals that fire posting functions when Payments and Expenses are saved or deleted.

We connect to post_save / post_delete on Payment and Expense.
Reversal entries are created on delete (keeping an audit trail).
"""
import logging

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)


def _post_payment_handler(payment):
    from apps.ledger.posting import post_payment
    try:
        post_payment(payment)
    except Exception as exc:
        logger.error("ledger: post_payment failed for Payment#%s: %s", payment.pk, exc)


def _reverse_payment_handler(payment):
    from apps.ledger.posting import reverse_payment
    try:
        reverse_payment(payment)
    except Exception as exc:
        logger.error("ledger: reverse_payment failed for Payment#%s: %s", payment.pk, exc)


def _post_expense_handler(expense):
    from apps.ledger.posting import post_expense
    try:
        if expense.category_id and expense.category.account_id:
            post_expense(expense)
        else:
            logger.warning(
                "ledger: Expense#%s has no GL account — skipping posting.", expense.pk
            )
    except Exception as exc:
        logger.error("ledger: post_expense failed for Expense#%s: %s", expense.pk, exc)


def _reverse_expense_handler(expense):
    from apps.ledger.posting import reverse_expense
    try:
        if expense.category_id and expense.category.account_id:
            reverse_expense(expense)
    except Exception as exc:
        logger.error("ledger: reverse_expense failed for Expense#%s: %s", expense.pk, exc)


# ── Payment signals ──────────────────────────────────────────────────────────

@receiver(post_save, sender="payments.Payment")
def on_payment_saved(sender, instance, created, **kwargs):
    """Post a journal entry when a Payment is created."""
    if created:
        _post_payment_handler(instance)


@receiver(post_delete, sender="payments.Payment")
def on_payment_deleted(sender, instance, **kwargs):
    """Create a reversal entry when a Payment is deleted (voided)."""
    _reverse_payment_handler(instance)


# ── Expense signals ──────────────────────────────────────────────────────────

@receiver(post_save, sender="expenses.Expense")
def on_expense_saved(sender, instance, created, **kwargs):
    """Post a journal entry when an Expense is created."""
    if created:
        _post_expense_handler(instance)


@receiver(post_delete, sender="expenses.Expense")
def on_expense_deleted(sender, instance, **kwargs):
    """Create a reversal entry when an Expense is deleted."""
    _reverse_expense_handler(instance)
