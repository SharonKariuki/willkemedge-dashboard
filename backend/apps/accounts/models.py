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
    AUDITOR = "auditor", "Auditor (read-only)"
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

    # Nobody signs themselves up. The owner or the superadmin invites a person
    # by email; the account exists but cannot sign in until they open the
    # emailed link and choose their own password (see AccountInvite).
    invited_by = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    invited_at = models.DateTimeField(null=True, blank=True)
    invite_accepted_at = models.DateTimeField(null=True, blank=True)
    #: Set when the account is switched off. Accounts are never deleted: the
    #: activity log and every payment they recorded still name them.
    deactivated_at = models.DateTimeField(null=True, blank=True)

    #: The buildings a caretaker looks after. A caretaker sees and works on
    #: these only; every other role sees the whole portfolio.
    buildings = models.ManyToManyField("buildings.Building", blank=True, related_name="caretakers")
    #: Access ends at the start of this day (Nairobi time). Required for an
    #: auditor - an audit is a visit, not a job - optional for anyone else.
    access_expires_on = models.DateField(null=True, blank=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    class Meta:
        db_table = "accounts_user"

    def __str__(self) -> str:
        return self.email

    @property
    def access_expired(self) -> bool:
        return bool(self.access_expires_on) and timezone.localdate() >= self.access_expires_on

    @property
    def status(self) -> str:
        """active | invited | expired | deactivated - what the Users page shows."""
        if self.deactivated_at:
            return "deactivated"
        if self.invited_at and not self.invite_accepted_at and not self.is_active:
            return "invited"
        if not self.is_active:
            return "deactivated"
        return "expired" if self.access_expired else "active"

    # What each role may do lives in apps.accounts.access; these read it, so
    # existing callers keep working. A superuser is the break-glass account
    # and carries every capability.
    def can(self, capability: str) -> bool:
        from .access import has_capability

        return has_capability(self, capability)

    @property
    def can_manage_users(self) -> bool:
        """Invite people, change their role, switch accounts off. Owner and superadmin."""
        from .access import Cap

        return self.can(Cap.MANAGE_USERS)

    @property
    def can_record_money(self) -> bool:
        from .access import Cap

        return self.can(Cap.RECORD_MONEY)

    @property
    def can_forgive_money(self) -> bool:
        from .access import Cap

        return self.can(Cap.FORGIVE_MONEY)


class AuditKind(models.TextChoices):
    #: A business action described in words by the code that took it
    #: ("Voided payment KES 12,000 — duplicate").
    EVENT = "event", "Action"
    #: A field-level change captured automatically on a tracked record. Several
    #: of these often sit under one EVENT from the same request.
    CHANGE = "change", "Record change"
    #: Sign-in, sign-out, failed sign-in, password reset.
    AUTH = "auth", "Sign-in"
    #: Someone tried to change something their role does not allow.
    DENIED = "denied", "Refused"


class AuditLog(models.Model):
    """Append-only record of what was done in the system, by whom, and from where.

    It began as the financial audit log (payments, arrears, credits) and keeps
    that table, so every row written since then is still here. It now also
    holds automatic field-level changes to tenants, units, buildings, expenses,
    water charges and users; sign-ins; refused actions; and the server commands
    that touch data. The director reads it on the Activity page.

    Append-only by policy: nothing in the codebase updates or deletes a row,
    and the admin registration is read-only.
    """

    actor = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_actions",
        help_text="Who performed the action. Null for system/automated actions.",
    )
    # Snapshots, so the row still says who it was after the user is renamed,
    # re-roled or deleted.
    actor_label = models.CharField(max_length=150, blank=True)
    actor_role = models.CharField(max_length=12, blank=True)

    kind = models.CharField(
        max_length=8, choices=AuditKind.choices, default=AuditKind.EVENT, db_index=True
    )
    action = models.CharField(
        max_length=60,
        help_text="Dotted action name, e.g. 'payment.void', 'unit.update'.",
    )
    object_type = models.CharField(max_length=40, help_text="Model acted on, e.g. 'payment'.")
    object_id = models.PositiveIntegerField(null=True, blank=True)
    object_label = models.CharField(
        max_length=150, blank=True, help_text="What the object was called at the time, e.g. 'MCF01'."
    )
    summary = models.CharField(max_length=255, help_text="Human-readable one-line description.")
    old_values = models.JSONField(default=dict, blank=True)
    new_values = models.JSONField(default=dict, blank=True)
    is_financial = models.BooleanField(
        default=False, help_text="Moves or changes money, rent, deposits or charges."
    )

    source = models.CharField(max_length=10, default="system", db_index=True)
    source_detail = models.CharField(
        max_length=120, blank=True, help_text="Command name, scheduled job, or request path."
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)
    session_id = models.CharField(
        max_length=32, blank=True, db_index=True,
        help_text="One per sign-in; every action taken under that sign-in shares it.",
    )
    request_id = models.CharField(
        max_length=32, blank=True, db_index=True,
        help_text="Rows written by the same request or command share this.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "accounts_financial_audit_log"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["object_type", "object_id"]),
            models.Index(fields=["action", "-created_at"]),
            models.Index(fields=["actor", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.action} by {self.actor_label or self.actor or 'system'}"


class LoginAttempt(models.Model):
    """Audit trail of every login attempt — successful and failed."""

    email = models.EmailField()
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=512, blank=True)
    successful = models.BooleanField(default=False)
    attempted_at = models.DateTimeField(auto_now_add=True)
    # Set on a failed attempt when a later correct sign-in resets the lockout
    # count. The row is kept: it is the record of the guessing.
    cleared_at = models.DateTimeField(null=True, blank=True)

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


class AccountInvite(models.Model):
    """The emailed link that lets an invited person choose their password.

    Single-use and short-lived, like a password reset, but longer: an invite
    may sit in an inbox over a weekend. Re-sending an invite retires the old
    link. Whoever holds the link sets the password, so the person who sent it
    never knows it.
    """

    user = models.ForeignKey("accounts.User", on_delete=models.CASCADE, related_name="invites")
    token = models.CharField(max_length=64, unique=True, db_index=True)
    created_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    used = models.BooleanField(default=False)

    EXPIRY_HOURS = 72

    class Meta:
        db_table = "accounts_account_invite"

    @classmethod
    def issue(cls, user, *, created_by=None) -> "AccountInvite":
        """A fresh link for ``user``; any earlier unused link stops working."""
        cls.objects.filter(user=user, used=False).update(used=True)
        return cls.objects.create(user=user, token=secrets.token_urlsafe(48), created_by=created_by)

    @property
    def expires_at(self):
        return self.created_at + timedelta(hours=self.EXPIRY_HOURS)

    @property
    def is_valid(self) -> bool:
        return not self.used and timezone.now() < self.expires_at and self.user.deactivated_at is None
