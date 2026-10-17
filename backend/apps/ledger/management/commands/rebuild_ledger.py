"""
Management command: rebuild_ledger

Restates the general ledger from its source records under the current posting
rules (see ``apps.ledger.rebuild``), then runs the integrity checks. A dry run
unless ``--apply``: it does the work inside a transaction, reports the trial
balance before and after, and rolls back.

Usage:
    python manage.py rebuild_ledger            # preview
    python manage.py rebuild_ledger --apply    # write it
"""
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Sum

from apps.ledger.checks import run_checks
from apps.ledger.rebuild import rebuild


class _DryRun(Exception):
    pass


def _balances():
    from apps.ledger.models import JournalLine

    return {
        r["account__code"]: (r["account__name"], (r["d"] or Decimal("0")) - (r["c"] or Decimal("0")))
        for r in JournalLine.objects.values("account__code", "account__name")
        .annotate(d=Sum("debit"), c=Sum("credit"))
    }


class Command(BaseCommand):
    help = "Restate the general ledger from its source records (dry run unless --apply)."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Write the restated ledger.")

    def handle(self, *args, **options):
        before = _balances()
        try:
            with transaction.atomic():
                done = rebuild()
                after = _balances()
                results = run_checks()
                if not options["apply"]:
                    raise _DryRun
        except _DryRun:
            self.stdout.write(self.style.WARNING("DRY RUN - nothing written. Re-run with --apply.\n"))

        self.stdout.write(self.style.MIGRATE_HEADING("Work done"))
        for what, n in sorted(done.items()):
            self.stdout.write(f"  {what:40} {n}")

        self.stdout.write(self.style.MIGRATE_HEADING("\nBalances (debit +, credit -)"))
        self.stdout.write(f"  {'account':48} {'before':>16} {'after':>16}")
        for code in sorted(set(before) | set(after)):
            name = (before.get(code) or after.get(code))[0]
            b = before.get(code, (name, Decimal("0")))[1]
            a = after.get(code, (name, Decimal("0")))[1]
            mark = "" if a == b else "  *"
            self.stdout.write(f"  {code} {name[:43]:43} {b:>16,.2f} {a:>16,.2f}{mark}")

        self.stdout.write(self.style.MIGRATE_HEADING("\nChecks after the rebuild"))
        for r in results:
            style = self.style.SUCCESS if r.ok else self.style.ERROR
            self.stdout.write(style(f"  {'PASS' if r.ok else 'FAIL'}  {r.name}: {r.detail}"))
