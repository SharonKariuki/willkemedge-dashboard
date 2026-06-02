"""Tests for the prune_auth_records management command."""
from datetime import timedelta
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.utils import timezone

from apps.accounts.models import LoginAttempt, PasswordResetToken

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(
        username="admin", email="admin@test.com", password="SecurePass123!"
    )


@pytest.mark.django_db
class TestPruneAuthRecords:
    def _old_attempt(self, days):
        attempt = LoginAttempt.objects.create(email="x@test.com", successful=False)
        LoginAttempt.objects.filter(pk=attempt.pk).update(
            attempted_at=timezone.now() - timedelta(days=days)
        )
        return attempt

    def test_deletes_old_login_attempts_only(self):
        old = self._old_attempt(days=120)
        recent = LoginAttempt.objects.create(email="y@test.com", successful=True)

        call_command("prune_auth_records", stdout=StringIO())

        assert not LoginAttempt.objects.filter(pk=old.pk).exists()
        assert LoginAttempt.objects.filter(pk=recent.pk).exists()

    def test_respects_custom_days(self):
        attempt = self._old_attempt(days=40)
        # Default 90 days keeps it...
        call_command("prune_auth_records", stdout=StringIO())
        assert LoginAttempt.objects.filter(pk=attempt.pk).exists()
        # ...but --days 30 removes it.
        call_command("prune_auth_records", "--days", "30", stdout=StringIO())
        assert not LoginAttempt.objects.filter(pk=attempt.pk).exists()

    def test_deletes_used_and_expired_tokens(self, user):
        used = PasswordResetToken.create_for_user(user)
        used.used = True
        used.save()

        expired = PasswordResetToken.create_for_user(user)
        PasswordResetToken.objects.filter(pk=expired.pk).update(
            created_at=timezone.now() - timedelta(minutes=30)
        )

        fresh = PasswordResetToken.create_for_user(user)

        call_command("prune_auth_records", stdout=StringIO())

        assert not PasswordResetToken.objects.filter(pk=used.pk).exists()
        assert not PasswordResetToken.objects.filter(pk=expired.pk).exists()
        assert PasswordResetToken.objects.filter(pk=fresh.pk).exists()

    def test_dry_run_deletes_nothing(self, user):
        old = self._old_attempt(days=120)
        token = PasswordResetToken.create_for_user(user)
        token.used = True
        token.save()

        out = StringIO()
        call_command("prune_auth_records", "--dry-run", stdout=out)

        assert LoginAttempt.objects.filter(pk=old.pk).exists()
        assert PasswordResetToken.objects.filter(pk=token.pk).exists()
        assert "dry-run" in out.getvalue()

    def test_idempotent(self):
        self._old_attempt(days=120)
        call_command("prune_auth_records", stdout=StringIO())
        out = StringIO()
        # Second run finds nothing to prune.
        call_command("prune_auth_records", stdout=out)
        assert "Pruned 0 LoginAttempt row(s)" in out.getvalue()
