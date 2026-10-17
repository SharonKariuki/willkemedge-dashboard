"""
Management command: check_ledger

Runs the ledger integrity checks (see ``apps.ledger.checks``) and prints a pass
or fail line for each. Exits non-zero when any check fails, so it can gate a
deploy or a scheduled job.

Usage:
    python manage.py check_ledger
"""
from django.core.management.base import BaseCommand, CommandError

from apps.ledger.checks import run_checks


class Command(BaseCommand):
    help = "Check that the general ledger agrees with the records it is built from."

    def handle(self, *args, **options):
        results = run_checks()
        for r in results:
            style = self.style.SUCCESS if r.ok else self.style.ERROR
            self.stdout.write(style(f"{'PASS' if r.ok else 'FAIL'}  {r.name}: {r.detail}"))
        failed = [r for r in results if not r.ok]
        if failed:
            raise CommandError(
                f"{len(failed)} ledger check(s) failed. "
                "`python manage.py rebuild_ledger --apply` restates the ledger from its records."
            )
