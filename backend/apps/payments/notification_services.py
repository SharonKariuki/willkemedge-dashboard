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

from django.utils import timezone

from apps.tenants.models import Tenant

from .models import NotificationChannel, NotificationStatus, TenantNotification
from .notifications import custom_email_html, send_email, send_sms

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


def _current_balance(tenant: Tenant) -> Decimal:
    """Total unpaid balance across all open arrears rows."""
    from django.db.models import Sum

    from .models import Arrears

    total = (
        Arrears.objects.filter(tenant=tenant, is_cleared=False)
        .aggregate(total=Sum("balance"))
        .get("total")
    )
    return total or Decimal("0")


def dispatch_notification(notification: TenantNotification) -> TenantNotification:
    """Render placeholders, send via the chosen channel, and record outcome."""
    tenant = notification.tenant
    rendered_body = _resolve_placeholders(notification.body, tenant)
    rendered_subject = _resolve_placeholders(notification.subject or "Notice", tenant)

    try:
        if notification.channel in (NotificationChannel.SMS, NotificationChannel.BOTH):
            if not tenant.phone:
                raise ValueError("Tenant has no phone number on file")
            send_sms(tenant.phone, rendered_body)

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

        notification.status = NotificationStatus.SENT
        notification.sent_at = timezone.now()
        notification.body = rendered_body
        notification.subject = rendered_subject
        notification.save(update_fields=["status", "sent_at", "body", "subject"])
        logger.info("Notification %s sent to %s", notification.id, tenant)
    except Exception as exc:
        notification.status = NotificationStatus.FAILED
        notification.error = str(exc)[:500]
        notification.save(update_fields=["status", "error"])
        logger.warning("Notification %s failed: %s", notification.id, exc)

    return notification
