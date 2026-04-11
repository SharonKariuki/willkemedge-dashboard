"""
Account-related services: lockout policy and login auditing.

Lockout policy: 5 failed attempts within 30 minutes locks the account
(by email) until the rolling window clears. We track this against
LoginAttempt rows so the audit log and the lockout share one source of truth.
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


def is_locked_out(email: str) -> bool:
    """Return True if there are >= LOCKOUT_THRESHOLD failed attempts in the window."""
    cutoff = timezone.now() - LOCKOUT_WINDOW
    failed_count = LoginAttempt.objects.filter(
        email=email.lower().strip(),
        successful=False,
        attempted_at__gte=cutoff,
    ).count()
    return failed_count >= LOCKOUT_THRESHOLD
