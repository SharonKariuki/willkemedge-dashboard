"""
Report any row that breaks a financial invariant the database now enforces.

Read-only. Run it against production BEFORE deploying the migration that
installs the CHECK constraints — the migration refuses to proceed on dirty
data (it will not silently rewrite an amount or a period), so this is how you
find out whether the deploy will go through.

    python manage.py check_db_invariants

Exit status is 1 when anything is broken, so it can gate a deploy step.

See ``config/db_invariants.py`` for the rules and why each one exists.
"""
from django.apps import apps as global_apps
from django.core.management.base import BaseCommand

from config.db_invariants import (
    duplicate_utility_charges,
    format_report,
    violations,
)


class Command(BaseCommand):
    help = "Report rows that break the database-level financial invariants."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit", type=int, default=10,
            help="How many offending ids to list per rule (default 10).",
        )

    def handle(self, *args, **options):
        limit = options["limit"]
        broken = violations(global_apps, limit=limit)
        dupes = duplicate_utility_charges(global_apps, limit=limit)

        if not broken and not dupes:
            self.stdout.write(self.style.SUCCESS(
                "All financial invariants hold. Safe to apply the constraint migration."
            ))
            return

        self.stdout.write(self.style.ERROR("Financial invariant violations found:\n"))
        self.stdout.write(format_report(broken, dupes))
        self.stdout.write("")
        self.stdout.write(
            "Nothing has been changed. Decide what each row should be, correct it\n"
            "deliberately (a void, a corrected charge, a data fix recorded in the\n"
            "audit log), then re-run this command before deploying."
        )
        raise SystemExit(1)
