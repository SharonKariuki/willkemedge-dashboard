"""
Nightly IPN reconciliation summary.

Schedule it from Render → New + → Cron Job:
    Command:  python manage.py send_daily_reconciliation
    Schedule: 0 3 * * *   (03:00 EAT every day — i.e. shortly after midnight)

Or run ad-hoc against a specific date:
    python manage.py send_daily_reconciliation --date 2026-05-30
"""
import datetime as dt

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Send the daily Co-op IPN reconciliation summary (yesterday by default)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            help="Date to report on, YYYY-MM-DD. Defaults to yesterday.",
        )

    def handle(self, *args, **options):
        from apps.payments.tasks import send_daily_reconciliation

        target_iso = options.get("date") or None
        if target_iso:
            try:
                dt.date.fromisoformat(target_iso)
            except ValueError as exc:
                raise CommandError(f"--date must be YYYY-MM-DD (got {target_iso!r})") from exc

        # Synchronous on purpose: cron jobs want a definite exit code.
        send_daily_reconciliation.apply(args=(target_iso,)).get()
        self.stdout.write(self.style.SUCCESS(
            f"Sent IPN reconciliation summary for {target_iso or 'yesterday'}."
        ))
