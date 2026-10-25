"""Stop a manual bulk send from reaching the same tenant twice.

Emailing statements to a property, or sending an SMS to many tenants, runs
inside one request. When that request outlived the browser's patience the
office saw "failed" while the server carried on sending, and a second click
sent everything again. Whatever the cause (a timeout, a double click, a
retry), a tenant who got the same message in the last few minutes is skipped
and reported as such, rather than messaged again.

Only earlier *manual* sends count (automatic runs carry a ``dedupe_key``): a
manual send is never swallowed as a duplicate of the monthly run. And only
the bulk endpoints use this; the single-tenant "Email statement" button always
sends, so a deliberate resend on a tenant's request still goes out.
"""
from datetime import timedelta

from django.utils import timezone

from .models import NotificationStatus, TenantNotification

REPEAT_WINDOW = timedelta(minutes=10)


def recently_sent(tenant_ids, *, channel: str, template_key: str = "", body: str | None = None) -> set[int]:
    """Ids of the tenants already sent this message within REPEAT_WINDOW.

    ``template_key`` identifies a kind of message (``rent_statement``); a
    hand-written one is matched on its ``body`` instead.
    """
    qs = TenantNotification.objects.filter(
        tenant_id__in=list(tenant_ids),
        channel=channel,
        status=NotificationStatus.SENT,
        dedupe_key="",
        created_at__gte=timezone.now() - REPEAT_WINDOW,
    )
    if template_key:
        qs = qs.filter(template_key=template_key)
    if body is not None:
        qs = qs.filter(body=body)
    return set(qs.values_list("tenant_id", flat=True))


def recent_bodies(tenant_ids, *, channel: str) -> set[tuple[int, str]]:
    """(tenant id, message text) pairs sent within REPEAT_WINDOW.

    For hand-written messages, whose text is personalised per tenant before it
    is stored: compare each tenant's rendered text against this set.
    """
    return set(
        TenantNotification.objects.filter(
            tenant_id__in=list(tenant_ids),
            channel=channel,
            status=NotificationStatus.SENT,
            dedupe_key="",
            created_at__gte=timezone.now() - REPEAT_WINDOW,
        ).values_list("tenant_id", "body")
    )


def skipped_entry(tenant) -> dict:
    """How a skipped tenant is reported back to the page."""
    return {
        "tenant": tenant.id,
        "tenant_name": tenant.full_name,
        "reason": "Already sent in the last 10 minutes — not repeated.",
    }
