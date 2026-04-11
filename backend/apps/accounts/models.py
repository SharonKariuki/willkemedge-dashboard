"""
Custom user model for the dashboard.

The system has a single admin user in v1, but we use a custom user model from
the start so we can extend it later without painful migrations.
"""
import secrets
from datetime import timedelta

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


class User(AbstractUser):
    """Single-owner admin user."""

    email = models.EmailField(unique=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    class Meta:
        db_table = "accounts_user"

    def __str__(self) -> str:
        return self.email


class LoginAttempt(models.Model):
    """Audit trail of every login attempt — successful and failed."""

    email = models.EmailField()
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=512, blank=True)
    successful = models.BooleanField(default=False)
    attempted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "accounts_login_attempt"
        indexes = [
            models.Index(fields=["email", "attempted_at"]),
            models.Index(fields=["ip_address", "attempted_at"]),
        ]
        ordering = ["-attempted_at"]


class PasswordResetToken(models.Model):
    """
    Single-use, time-limited password reset token.
    Expires after 15 minutes. Consumed on first use.
    """
    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="reset_tokens",
    )
    token = models.CharField(max_length=64, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    used = models.BooleanField(default=False)

    EXPIRY_MINUTES = 15

    class Meta:
        db_table = "accounts_password_reset_token"

    @classmethod
    def create_for_user(cls, user) -> "PasswordResetToken":
        """Generate a secure random token for the user."""
        return cls.objects.create(user=user, token=secrets.token_urlsafe(48))

    @property
    def is_valid(self) -> bool:
        expiry = self.created_at + timedelta(minutes=self.EXPIRY_MINUTES)
        return not self.used and timezone.now() < expiry
