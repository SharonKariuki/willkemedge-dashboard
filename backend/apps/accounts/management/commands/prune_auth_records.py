"""
Prune stale authentication audit records.

Deletes:
  - LoginAttempt rows older than N days (default 90).
  - PasswordResetToken rows that are used OR expired.

Both tables grow unbounded otherwise. The command is idempotent: running it
repeatedly only removes rows that match the age/used/expired criteria, and a
second run with nothing to prune simply reports zero deletions.

Usage:
    python manage.py prune_auth_records [--days 90] [--dry-run]
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import F
from django.utils import timezone

from apps.accounts.models import LoginAttempt, PasswordResetToken


class Command(BaseCommand):
    help = "Delete old LoginAttempt rows and used/expired PasswordResetToken rows."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=90,
            help="Delete LoginAttempt rows older than this many days (default: 90).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be deleted without deleting anything.",
        )

    def handle(self, *args, **options):
        days = options["days"]
        dry_run = options["dry_run"]
        now = timezone.now()

        cutoff = now - timedelta(days=days)
        old_attempts = LoginAttempt.objects.filter(attempted_at__lt=cutoff)

        # A token is prunable if it has been used, or if its expiry window
        # (created_at + EXPIRY_MINUTES) is now in the past.
        expiry = timedelta(minutes=PasswordResetToken.EXPIRY_MINUTES)
        stale_tokens = PasswordResetToken.objects.filter(used=True) | (
            PasswordResetToken.objects.annotate(
                expires_at=F("created_at") + expiry
            ).filter(expires_at__lt=now)
        )
        stale_tokens = stale_tokens.distinct()

        attempt_count = old_attempts.count()
        token_count = stale_tokens.count()

        if dry_run:
            self.stdout.write(
                f"[dry-run] Would delete {attempt_count} LoginAttempt row(s) "
                f"older than {days} day(s) and {token_count} used/expired "
                f"PasswordResetToken row(s)."
            )
            return

        old_attempts.delete()
        # Re-evaluate token queryset before delete to avoid OR/annotate delete
        # restrictions; collect ids first.
        token_ids = list(stale_tokens.values_list("pk", flat=True))
        PasswordResetToken.objects.filter(pk__in=token_ids).delete()

        self.stdout.write(
            self.style.SUCCESS(
                f"Pruned {attempt_count} LoginAttempt row(s) and "
                f"{token_count} PasswordResetToken row(s)."
            )
        )
