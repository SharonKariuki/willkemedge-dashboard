"""
Management command: backfill_ledger

Posts a journal entry for every existing Payment and Expense that has no
ledger entry yet. Safe to run repeatedly — idempotent by design.

Usage:
    python manage.py backfill_ledger
    python manage.py backfill_ledger --dry-run
"""
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models import Sum


class Command(BaseCommand):
    help = "Backfill double-entry journal entries for all existing Payments and Expenses."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be posted without writing to the database.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        from apps.expenses.models import Expense
        from apps.ledger.models import JournalEntry
        from apps.ledger.posting import post_expense, post_payment
        from apps.payments.models import Payment

        self.stdout.write(self.style.MIGRATE_HEADING("=== Ledger Backfill ==="))
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no changes will be written.\n"))

        # ── Payments ────────────────────────────────────────────────────────
        already_posted_payments = set(
            JournalEntry.objects.filter(source_type="payment", kind="normal")
            .values_list("source_id", flat=True)
        )
        payments_qs = (
            Payment.objects.select_related(
                "tenant", "tenant__unit", "tenant__unit__building"
            )
            .exclude(pk__in=already_posted_payments)
        )
        payment_count = payments_qs.count()
        self.stdout.write(f"Payments to post: {payment_count}")

        created_payments = 0
        skipped_payments = 0
        for payment in payments_qs.iterator(chunk_size=200):
            if dry_run:
                self.stdout.write(
                    f"  [DRY] Would post Payment#{payment.pk} "
                    f"{payment.payment_type} KES {payment.amount}"
                )
                created_payments += 1
                continue
            try:
                post_payment(payment)
                created_payments += 1
            except Exception as exc:
                self.stderr.write(
                    f"  SKIP Payment#{payment.pk}: {exc}"
                )
                skipped_payments += 1

        # ── Expenses ────────────────────────────────────────────────────────
        already_posted_expenses = set(
            JournalEntry.objects.filter(source_type="expense", kind="normal")
            .values_list("source_id", flat=True)
        )
        expenses_qs = (
            Expense.objects.select_related("category", "category__account", "building")
            .exclude(pk__in=already_posted_expenses)
            .filter(category__account__isnull=False)
        )
        expense_count = expenses_qs.count()
        self.stdout.write(f"Expenses to post: {expense_count}")

        created_expenses = 0
        skipped_expenses = 0
        for expense in expenses_qs.iterator(chunk_size=200):
            if dry_run:
                self.stdout.write(
                    f"  [DRY] Would post Expense#{expense.pk} "
                    f"{expense.category.name} KES {expense.amount}"
                )
                created_expenses += 1
                continue
            try:
                post_expense(expense)
                created_expenses += 1
            except Exception as exc:
                self.stderr.write(
                    f"  SKIP Expense#{expense.pk}: {exc}"
                )
                skipped_expenses += 1

        # ── Summary ─────────────────────────────────────────────────────────
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"Payment entries {'would be ' if dry_run else ''}created:  {created_payments}"
        ))
        if skipped_payments:
            self.stdout.write(self.style.WARNING(f"Payment entries skipped: {skipped_payments}"))
        self.stdout.write(self.style.SUCCESS(
            f"Expense entries {'would be ' if dry_run else ''}created:  {created_expenses}"
        ))
        if skipped_expenses:
            self.stdout.write(self.style.WARNING(f"Expense entries skipped: {skipped_expenses}"))

        if not dry_run:
            self._report_trial_balance()

    def _report_trial_balance(self):

        from apps.ledger.models import JournalLine

        agg = JournalLine.objects.aggregate(
            total_debit=Sum("debit"),
            total_credit=Sum("credit"),
        )
        total_debit = agg["total_debit"] or Decimal("0")
        total_credit = agg["total_credit"] or Decimal("0")
        balanced = abs(total_debit - total_credit) < Decimal("0.01")

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Trial Balance (post-backfill):"))
        self.stdout.write(f"  Total Debits:  KES {total_debit:,.2f}")
        self.stdout.write(f"  Total Credits: KES {total_credit:,.2f}")
        if balanced:
            self.stdout.write(self.style.SUCCESS("  ✓ Trial balance is BALANCED"))
        else:
            diff = total_debit - total_credit
            self.stdout.write(self.style.ERROR(
                f"  ✗ Trial balance is OUT OF BALANCE by KES {diff:,.2f}"
            ))
