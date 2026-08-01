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


class Role(models.TextChoices):
    """Who may do what. Ordered most- to least-privileged.

    Segregation of duties: recording money and *forgiving* money are
    deliberately different privileges, so the person entering receipts cannot
    also write debt off. Only the OWNER (the director) may waive or void.
    """
    OWNER = "owner", "Owner / Director"
    ACCOUNTANT = "accountant", "Accountant"
    CARETAKER = "caretaker", "Caretaker"
    VIEWER = "viewer", "Viewer (read-only)"


#: Roles allowed to record a payment or reconcile a bank credit.
ROLES_RECORD_MONEY = frozenset({Role.OWNER, Role.ACCOUNTANT})
#: Roles allowed to forgive or unwind money (waive arrears, void a payment).
ROLES_FORGIVE_MONEY = frozenset({Role.OWNER})


class User(AbstractUser):
    """Dashboard user. `role` drives every write permission on money."""

    email = models.EmailField(unique=True)
    role = models.CharField(
        max_length=12,
        choices=Role.choices,
        default=Role.VIEWER,
        help_text=(
            "Least privilege by default: a new account can read but not record, "
            "waive, or void anything until it is explicitly promoted."
        ),
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    class Meta:
        db_table = "accounts_user"

    def __str__(self) -> str:
        return self.email

    # A superuser is the break-glass account and always carries owner rights.
    @property
    def can_record_money(self) -> bool:
        return self.is_superuser or self.role in ROLES_RECORD_MONEY

    @property
    def can_forgive_money(self) -> bool:
        return self.is_superuser or self.role in ROLES_FORGIVE_MONEY


class FinancialAuditLog(models.Model):
    """Append-only record of every money-affecting action and who took it.

    Payments, arrears and journal entries carry no history of their own, so a
    corrected amount or a written-off debt used to leave no trace of who did it
    or what the figure was before. Every such action writes one row here.

    Append-only by policy: nothing in the codebase updates or deletes a row,
    and the admin registration is read-only.
    """

    actor = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="financial_actions",
        help_text="Who performed the action. Null for system/automated actions.",
    )
    action = models.CharField(
        max_length=40,
        help_text="Dotted action name, e.g. 'payment.void', 'arrears.waive'.",
    )
    object_type = models.CharField(max_length=30, help_text="Model acted on, e.g. 'payment'.")
    object_id = models.PositiveIntegerField(null=True, blank=True)
    summary = models.CharField(max_length=255, help_text="Human-readable one-line description.")
    old_values = models.JSONField(default=dict, blank=True)
    new_values = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "accounts_financial_audit_log"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["object_type", "object_id"]),
            models.Index(fields=["action", "-created_at"]),
            models.Index(fields=["actor", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.action} by {self.actor or 'system'}"


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
