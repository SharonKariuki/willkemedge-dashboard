"""
Put maintenance costs that never reached the ledger onto the books.

Until the fix in ``apps.buildings.maintenance``, a costed maintenance request
created its expense under a category called "Maintenance & Repairs" — made on
the fly, with no GL account. The ledger signal skips any expense whose
category has no account, so those costs were on the Expenses page and missing
from the general ledger, the P&L and the trial balance.

What it changes
---------------
Every expense created by a maintenance request is moved to the COA's
"Repairs & Maintenance" category (GL 5200) and, if it has no journal entry,
posted (DR 5200 / CR the payment account), dated the expense's own date.

The stray "Maintenance & Repairs" category is then deleted, if nothing still
uses it, so it stops appearing in the expense dropdown.

DRY-RUN BY DEFAULT. Nothing is written without --apply. Re-running is safe:
once moved and posted, an expense drops off the list.

Usage:
    python manage.py repair_maintenance_expenses
    python manage.py repair_maintenance_expenses --apply
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import ProtectedError

STRAY_CATEGORY = "Maintenance & Repairs"


class Command(BaseCommand):
    help = (
        "Move maintenance-request expenses onto GL 5200 and post the ones "
        "missing from the ledger. Dry-run unless --apply."
    )

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Write the changes.")

    def handle(self, *args, **opts):
        from apps.buildings.maintenance import MAINTENANCE_CATEGORY
        from apps.expenses.models import Expense, ExpenseCategory
        from apps.ledger.models import JournalEntry
        from apps.ledger.posting import post_expense

        apply = opts["apply"]
        target = (
            ExpenseCategory.objects.filter(name=MAINTENANCE_CATEGORY, account__isnull=False)
            .select_related("account")
            .first()
        )
        if target is None:
            raise CommandError(
                f"'{MAINTENANCE_CATEGORY}' category missing or unmapped — run seed_coa first."
            )

        posted_ids = set(
            JournalEntry.objects.filter(source_type="expense", kind="normal")
            .values_list("source_id", flat=True)
        )
        expenses = (
            Expense.objects.filter(maintenance_request__isnull=False)
            .select_related("category", "unit")
            .order_by("date", "pk")
        )

        moved = posted = 0
        with transaction.atomic():
            for expense in expenses:
                wrong_category = expense.category_id != target.pk
                unposted = expense.pk not in posted_ids
                if not (wrong_category or unposted):
                    continue
                self.stdout.write(
                    f"  Expense #{expense.pk} {expense.date} KES {expense.amount} "
                    f"({expense.unit.label if expense.unit else '-'}): "
                    + ", ".join(filter(None, [
                        f"category '{expense.category.name}' → '{target.name}'" if wrong_category else "",
                        "post to ledger" if unposted else "",
                    ]))
                )
                if not apply:
                    moved += wrong_category
                    posted += unposted
                    continue
                if wrong_category:
                    expense.category = target
                    # The post_save signal posts it now that the category maps.
                    expense.save(update_fields=["category", "updated_at"])
                    moved += 1
                if unposted:
                    already = JournalEntry.objects.filter(
                        source_type="expense", source_id=expense.pk, kind="normal"
                    ).exists()
                    if not already:
                        # Raised, not swallowed like the signal: a failure here
                        # rolls the whole repair back rather than half-applying it.
                        post_expense(expense)
                    posted += 1

            stray = ExpenseCategory.objects.filter(
                name__iexact=STRAY_CATEGORY, account__isnull=True
            ).first()
            if stray is not None:
                left = Expense.objects.filter(category=stray).exclude(
                    maintenance_request__isnull=False
                ).count()
                if left:
                    self.stdout.write(self.style.WARNING(
                        f"  '{stray.name}' still has {left} hand-entered expense(s); "
                        f"left in place — recategorise them on the Expenses page."
                    ))
                elif apply:
                    try:
                        stray.delete()
                        self.stdout.write(f"  Deleted stray category '{stray.name}'.")
                    except ProtectedError:
                        self.stdout.write(self.style.WARNING(
                            f"  '{stray.name}' is still referenced elsewhere; left in place."
                        ))
                else:
                    self.stdout.write(f"  Would delete stray category '{stray.name}'.")

            if not apply:
                transaction.set_rollback(True)

        verb = "Applied" if apply else "Dry run —"
        self.stdout.write(self.style.SUCCESS(
            f"{verb} {moved} expense(s) recategorised, {posted} posted to the ledger."
            + ("" if apply else " Re-run with --apply to write.")
        ))
