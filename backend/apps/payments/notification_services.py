"""
Service for composing and dispatching tenant notifications.

dispatch_notification() renders the body with tenant-specific placeholders,
attempts to send via the selected channel(s), and records the outcome on
the TenantNotification row. Failures are swallowed per-recipient so a
broken phone/email doesn't abort a batch send.
"""
from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

from django.conf import settings
from django.utils import timezone

from apps.tenants.models import Tenant

from .models import NotificationChannel, NotificationStatus, TenantNotification
from .notifications import at_delivery_error, custom_email_html, send_email, send_sms

logger = logging.getLogger(__name__)


def _resolve_placeholders(text: str, tenant: Tenant) -> str:
    """Replace {placeholders} with values from the tenant's current state."""
    now = timezone.now()
    balance = _current_balance(tenant)
    amount = tenant.monthly_rent
    due_day = getattr(tenant, "due_day", 5)
    due_date = date(now.year, now.month, due_day).isoformat()

    values = {
        "tenant_name": tenant.full_name,
        "first_name": tenant.first_name,
        "unit_label": tenant.unit.label if tenant.unit_id else "",
        "building_name": tenant.unit.building.name if tenant.unit_id else "",
        "month": now.month,
        "year": now.year,
        "amount": f"{amount:,.0f}",
        "balance": f"{balance:,.0f}",
        "due_date": due_date,
    }
    try:
        return text.format(**values)
    except (KeyError, IndexError, ValueError):
        return text


def _at_message_id(receipt: dict) -> str:
    """Pull the messageId out of an Africa's Talking send response, if present.

    Shape: {"SMSMessageData": {"Recipients": [{"messageId": "ATXid_…", …}]}}.
    """
    try:
        recipients = receipt["SMSMessageData"]["Recipients"]
        return str(recipients[0].get("messageId", ""))[:120] if recipients else ""
    except (KeyError, IndexError, TypeError):
        return ""


def _current_balance(tenant: Tenant) -> Decimal:
    """Total unpaid balance across the open arrears rows that have fallen due.

    Periods after the current month are excluded. Billing runs a month ahead of
    the calendar (see billing_calendar), so from the 25th every tenant carries a
    row for next month; counting it here would have every reminder SMS quote a
    balance a full month's rent too high for the last week of every month.
    """
    from django.db.models import Sum

    from .models import Arrears
    from .monthly_ledger import upto_current_period

    total = (
        Arrears.objects.filter(tenant=tenant, is_cleared=False)
        .filter(upto_current_period(timezone.localdate()))
        .aggregate(total=Sum("balance"))
        .get("total")
    )
    return total or Decimal("0")


def dispatch_notification(
    notification: TenantNotification, *, automatic: bool = True
) -> TenantNotification:
    """Render placeholders, send via the chosen channel, and record outcome.

    ``automatic`` marks a send the system decided to make on its own — rent and
    arrears reminders. Those are what TENANT_NOTIFICATIONS_ENABLED silences.
    The admin broadcast form passes ``automatic=False``: a person chose to send
    it, knows they did, and sees the result immediately, so it stays available
    while automatic messaging is paused.
    """
    tenant = notification.tenant
    rendered_body = _resolve_placeholders(notification.body, tenant)
    rendered_subject = _resolve_placeholders(notification.subject or "Notice", tenant)
    notification.body = rendered_body
    notification.subject = rendered_subject

    # Master switch, automatic sends only. Left PENDING rather than SENT or
    # FAILED: nothing was delivered and nothing went wrong, so the row stays a
    # truthful record of a message still owed to the tenant — and can be
    # re-dispatched once notifications are switched back on.
    if automatic and not getattr(settings, "TENANT_NOTIFICATIONS_ENABLED", True):
        logger.info(
            "Notification %s suppressed for tenant %s: TENANT_NOTIFICATIONS_ENABLED=false",
            notification.id, tenant.id,
        )
        notification.status = NotificationStatus.PENDING
        notification.error = "Suppressed: tenant notifications are disabled"
        notification.save()
        return notification

    error: str | None = None
    try:
        if notification.channel in (NotificationChannel.SMS, NotificationChannel.BOTH):
            if not tenant.phone:
                raise ValueError("Tenant has no phone number on file")
            sms_receipt = send_sms(tenant.phone, rendered_body)
            if sms_receipt is not None:
                # Persist the Africa's Talking delivery receipt (status, cost,
                # messageId) for auditing.
                notification.provider_response = str(sms_receipt)[:5000]
                notification.provider_message_id = _at_message_id(sms_receipt)
                # AT answers with HTTP 200 even when the carrier rejects the
                # recipient (e.g. UserInBlacklist), so send_sms cannot raise on
                # it. Read the per-recipient status so a blocked message is
                # recorded as FAILED, not a false 'sent'.
                error = at_delivery_error(sms_receipt)

        if notification.channel in (NotificationChannel.EMAIL, NotificationChannel.BOTH):
            if tenant.email:
                send_email(
                    tenant.email,
                    rendered_subject,
                    custom_email_html(rendered_subject, rendered_body),
                    text_content=rendered_body,
                )
            elif notification.channel == NotificationChannel.EMAIL:
                raise ValueError("Tenant has no email address on file")
    except Exception as exc:
        error = str(exc)[:500]
        logger.warning("Notification %s failed: %s", notification.id, exc)

    if error:
        notification.status = NotificationStatus.FAILED
        notification.error = error
    else:
        notification.status = NotificationStatus.SENT
        notification.sent_at = timezone.now()
        logger.info("Notification %s sent to %s", notification.id, tenant)

    notification.save()
    return notification
