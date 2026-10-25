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
import ipaddress
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from .models import LoginAttempt

LOCKOUT_THRESHOLD = 5
LOCKOUT_WINDOW = timedelta(minutes=30)


def forwarded_chain(request) -> list[str]:
    """The X-Forwarded-For entries, left (claimed origin) to right (last hop)."""
    raw = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return [part.strip() for part in raw.split(",") if part.strip()]


def get_client_ip(request) -> str | None:
    """The caller's IP, as far as the proxies in front of us can vouch for it.

    The leftmost X-Forwarded-For entry is whatever the client sent: Render's
    proxy appends to the header rather than replacing it, so trusting the
    leftmost value let anyone pick a fresh fake IP per request and walk past
    the lockout. Two settings say what to trust instead:

    * ``CLIENT_IP_HEADER`` — a META key set by a proxy that overwrites it
      (e.g. ``HTTP_CF_CONNECTING_IP``). Used first when present.
    * ``TRUSTED_PROXY_HOPS`` — how many proxies append to X-Forwarded-For;
      the client IP is that many entries from the right.

    With neither set the old leftmost behaviour stays, so nothing changes
    until production is configured (see ClientIpDebugView).
    """
    if request is None:
        return None
    return _valid_ip(_raw_client_ip(request))


def _raw_client_ip(request) -> str | None:
    header = getattr(settings, "CLIENT_IP_HEADER", "")
    if header and request.META.get(header):
        return request.META[header].split(",")[0].strip()
    chain = forwarded_chain(request)
    if chain:
        hops = getattr(settings, "TRUSTED_PROXY_HOPS", None)
        if hops is None:
            return chain[0]
        if hops >= 1 and len(chain) >= hops:
            return chain[-hops]
    return request.META.get("REMOTE_ADDR")


def _valid_ip(value: str | None) -> str | None:
    """The address if it parses, else None. ``ip_address`` is a Postgres inet
    column, so a junk header value would otherwise fail the whole login."""
    if not value:
        return None
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None


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
        cleared_at__isnull=True,
        attempted_at__gte=cutoff,
    ).count()
    return failed_count >= LOCKOUT_THRESHOLD


def clear_failed_attempts(email: str) -> int:
    """Reset the rolling failed-attempt window for an email after a success.

    A user who fails a few times and then authenticates correctly should not
    remain one slip away from a lockout. The in-window failures are marked
    cleared, not deleted: they are the evidence of a guessing attempt that
    happened to precede a real sign-in, and the login audit must keep them.
    Returns the number of rows cleared.
    """
    cutoff = timezone.now() - LOCKOUT_WINDOW
    return LoginAttempt.objects.filter(
        email=email.lower().strip(),
        successful=False,
        cleared_at__isnull=True,
        attempted_at__gte=cutoff,
    ).update(cleared_at=timezone.now())
