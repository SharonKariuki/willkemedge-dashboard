"""
Replay ledger postings that previously failed.

The posting signals capture a failed post/reverse in a PostingFailure row
rather than silently dropping it (see apps/ledger/signals.py). This command
walks the open failures and re-attempts each one, so cash that briefly went
un-booked (e.g. during a transient DB error or before a GL account was seeded)
is reconciled into the books.

Usage
-----
    python manage.py retry_posting_failures            # replay all open failures
    python manage.py retry_posting_failures --dry-run  # report only, change nothing
"""
from django.core.management.base import BaseCommand
from django.utils import timezone


def _source_registry():
    """Map source_type → (Model, post_fn, reverse_fn). Imported lazily so the
    command module stays import-safe at app-load time."""
    from apps.expenses.models import Expense, ManualIncome
    from apps.ledger import posting
    from apps.payments.models import Payment, UtilityCharge

    return {
        "payment": (Payment, posting.post_payment, posting.reverse_payment),
        "expense": (Expense, posting.post_expense, posting.reverse_expense),
        "manual_income": (ManualIncome, posting.post_manual_income, posting.reverse_manual_income),
        "utility_charge": (UtilityCharge, posting.post_utility_charge, None),
    }


class Command(BaseCommand):
    help = "Replay ledger postings recorded as failed in PostingFailure."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List open failures without attempting to re-post.",
        )

    def handle(self, *args, **options):
        from apps.ledger.models import PostingFailure

        registry = _source_registry()
        dry_run = options["dry_run"]

        open_failures = PostingFailure.objects.filter(resolved=False).order_by("created_at")
        total = open_failures.count()
        if total == 0:
            self.stdout.write(self.style.SUCCESS("No open posting failures."))
            return

        self.stdout.write(f"{total} open posting failure(s).")
        resolved = replayed = missing = still_failing = 0

        for failure in open_failures:
            label = f"{failure.operation} {failure.source_type}#{failure.source_id} ({failure.kind})"
            entry = registry.get(failure.source_type)
            if entry is None:
                self.stderr.write(f"  ? {label}: unknown source_type — skipped")
                continue

            model, post_fn, reverse_fn = entry
            instance = model.objects.filter(pk=failure.source_id).first()

            if instance is None:
                # The source row is gone; there is nothing left to post. Resolve
                # so it stops showing as an open failure.
                missing += 1
                self.stdout.write(f"  - {label}: source no longer exists")
                if not dry_run:
                    failure.resolved = True
                    failure.resolved_at = timezone.now()
                    failure.error = "source row deleted before replay"
                    failure.save(update_fields=["resolved", "resolved_at", "error", "updated_at"])
                    resolved += 1
                continue

            if dry_run:
                self.stdout.write(f"  · {label}: would replay")
                continue

            try:
                if failure.operation == "reverse":
                    if reverse_fn is None:
                        raise ValueError(f"No reverse handler for {failure.source_type}")
                    reverse_fn(instance)
                else:
                    post_fn(instance, replace=True)
            except Exception as exc:  # noqa: BLE001 — report and keep going
                still_failing += 1
                failure.error = str(exc)[:2000]
                failure.attempts += 1
                failure.save(update_fields=["error", "attempts", "updated_at"])
                self.stderr.write(self.style.ERROR(f"  ✗ {label}: {exc}"))
            else:
                replayed += 1
                resolved += 1
                failure.resolved = True
                failure.resolved_at = timezone.now()
                failure.save(update_fields=["resolved", "resolved_at", "updated_at"])
                self.stdout.write(self.style.SUCCESS(f"  ✓ {label}: reposted"))

        if dry_run:
            self.stdout.write("Dry run — no changes made.")
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Done. replayed={replayed} resolved={resolved} "
                    f"missing={missing} still_failing={still_failing}"
                )
            )
