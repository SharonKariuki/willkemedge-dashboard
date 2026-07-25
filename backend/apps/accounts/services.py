"""
Account-related services: lockout policy and login auditing.

Lockout policy: 5 failed attempts within 30 minutes from the SAME source IP
lock that email/IP pair until the rolling window clears. We track this against
LoginAttempt rows so the audit log and the lockout share one source of truth.

The lock is scoped to (email, IP) rather than email alone: keying on email
only let an unauthenticated attacker lock any known admin email on demand by
firing five bad passwords (a denial-of-service against the single operator).
Scoping to the source IP still slows a single-source brute force while a real
user signing in from a different IP is never locked out by someone else.
"""
from datetime import timedelta

from django.utils import timezone

from .models import LoginAttempt

LOCKOUT_THRESHOLD = 5
LOCKOUT_WINDOW = timedelta(minutes=30)


def get_client_ip(request) -> str | None:
    if request is None:
        return None
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def get_user_agent(request) -> str:
    if request is None:
        return ""
    return (request.META.get("HTTP_USER_AGENT") or "")[:512]


def record_login_attempt(*, email: str, request, successful: bool) -> LoginAttempt:
    return LoginAttempt.objects.create(
        email=email.lower().strip(),
        ip_address=get_client_ip(request),
        user_agent=get_user_agent(request),
        successful=successful,
    )


def is_locked_out(email: str, ip_address: str | None = None) -> bool:
    """Return True if the (email, ip_address) pair has >= LOCKOUT_THRESHOLD failed
    attempts in the window.

    Scoping to the source IP prevents a lockout DoS: a bad actor at one IP can
    no longer lock a victim's email for everyone else — only the requesting IP's
    own failed attempts against that email are counted.
    """
    cutoff = timezone.now() - LOCKOUT_WINDOW
    failed_count = LoginAttempt.objects.filter(
        email=email.lower().strip(),
        ip_address=ip_address,
        successful=False,
        attempted_at__gte=cutoff,
    ).count()
    return failed_count >= LOCKOUT_THRESHOLD


def clear_failed_attempts(email: str) -> int:
    """Reset the rolling failed-attempt window for an email after a success.

    A user who fails a few times and then authenticates correctly should not
    remain one slip away from a lockout. We mark the in-window failed attempts
    as resolved by deleting them (the successful LoginAttempt row remains as
    the audit record). Returns the number of failed rows cleared.
    """
    cutoff = timezone.now() - LOCKOUT_WINDOW
    deleted, _ = LoginAttempt.objects.filter(
        email=email.lower().strip(),
        successful=False,
        attempted_at__gte=cutoff,
    ).delete()
    return deleted
