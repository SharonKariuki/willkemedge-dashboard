"""
Emailing a tenant their rent statement as a PDF.

One function, `send_tenant_statement`, used by all three callers so a statement
looks the same however it was triggered:

  * the monthly run          — `tasks.send_monthly_statements`
  * a single manual send     — `POST /api/tenants/{id}/email-statement/`
  * a bulk manual send       — `POST /api/tenants/email-statements/`

Every send is recorded as a `TenantNotification` on the EMAIL channel, so the
Notifications page shows who was written to and a failed address can be found
and retried rather than silently dropping out of the run.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.utils import timezone

from .models import NotificationChannel, NotificationStatus, TenantNotification

logger = logging.getLogger(__name__)


def statement_dedupe_key(tenant_id: int, period) -> str:
    """Idempotency marker for the monthly run: one statement per tenant per month.

    Manual sends deliberately pass no key — re-sending a statement on request is
    a normal thing for the office to do, and must not be swallowed as a duplicate.
    """
    return f"statement:{tenant_id}:{period:%Y-%m}"


def _summary_line(tenant, statement: dict) -> str:
    """Short plain-text record of what was sent, for the notification history.

    The email body itself is a full HTML statement running to several hundred
    lines; storing that on every row would make the notifications list unusable.
    """
    return (
        f"Rent statement as at {statement['statement_date']} for "
        f"{tenant.unit.building.name} {tenant.unit.label} — balance KES "
        f"{statement['total_due']}, payable on or before {statement['due_date']}."
    )


def send_tenant_statement(
    tenant,
    *,
    statement_date=None,
    automatic: bool = True,
    created_by=None,
    dedupe_key: str = "",
) -> TenantNotification:
    """Email one tenant their rent statement with the PDF attached.

    Returns the `TenantNotification` recording the outcome — SENT, FAILED with
    the reason, or PENDING when an automatic send was suppressed. Never raises
    on a per-tenant problem (no email, no unit, SMTP refusal), so one bad row
    cannot abort a batch; the caller reads `status` to count what happened.

    `automatic` marks a send the system decided to make on its own — the monthly
    run. Those are what TENANT_NOTIFICATIONS_ENABLED silences. A manual send
    passes automatic=False: a person chose it and is watching the result, so it
    stays available while automatic messaging is paused. Same rule as
    `notification_services.dispatch_notification`.
    """
    from .notifications import send_email, statement_email_html
    from .pdf_service import render_to_pdf
    from .statement_service import build_statement

    notification = TenantNotification(
        tenant=tenant,
        channel=NotificationChannel.EMAIL,
        template_key="rent_statement",
        dedupe_key=dedupe_key,
        created_by=created_by,
        status=NotificationStatus.PENDING,
        subject="Rent Statement",
        body="",
    )

    if not tenant.unit_id:
        notification.status = NotificationStatus.FAILED
        notification.error = "Tenant has no unit assigned"
        notification.save()
        return notification

    if not tenant.email:
        notification.status = NotificationStatus.FAILED
        notification.error = "Tenant has no email address on file"
        notification.save()
        return notification

    statement = build_statement(tenant, statement_date=statement_date)
    notification.subject = (
        f"Rent Statement – {tenant.unit.building.name} {tenant.unit.label} – "
        f"{statement['statement_date']}"
    )
    notification.body = _summary_line(tenant, statement)

    # Master switch, automatic sends only. Left PENDING rather than SENT or
    # FAILED: nothing was delivered and nothing went wrong, so the row stays a
    # truthful record of a statement still owed to the tenant.
    if automatic and not getattr(settings, "TENANT_NOTIFICATIONS_ENABLED", True):
        notification.error = "Suppressed: tenant notifications are disabled"
        notification.save()
        logger.info(
            "Statement for tenant %s suppressed: TENANT_NOTIFICATIONS_ENABLED=false",
            tenant.id,
        )
        return notification

    html = statement_email_html(tenant.full_name, statement)

    # The HTML body already carries the whole statement, so a PDF that fails to
    # render costs the tenant the attachment, not the statement. Send anyway and
    # log it — same call the payment receipt makes in tasks._notify_tenant_payment.
    attachments = []
    pdf = render_to_pdf("payments/statement_pdf.html", statement)
    if pdf:
        safe_name = tenant.full_name.replace(" ", "_")
        attachments.append((f"Rent_Statement_{safe_name}.pdf", pdf, "application/pdf"))
    else:
        logger.warning(
            "Statement PDF failed to render for tenant %s — emailing without the attachment",
            tenant.id,
        )

    try:
        delivered = send_email(
            tenant.email,
            notification.subject,
            html,
            text_content=notification.body,
            attachments=attachments,
        )
    except Exception as exc:
        notification.status = NotificationStatus.FAILED
        notification.error = str(exc)[:500]
        notification.save()
        logger.warning("Statement email failed for tenant %s: %s", tenant.id, exc)
        return notification

    # No SMTP credentials means nothing left the building. Recording that as
    # SENT would report a whole statement run as delivered to a mailbox that was
    # never opened, so it is a failure the office can see and re-run.
    if not delivered:
        notification.status = NotificationStatus.FAILED
        notification.error = "Email is not configured (EMAIL_HOST_USER / EMAIL_HOST_PASSWORD unset)"
        notification.save()
        return notification

    notification.status = NotificationStatus.SENT
    notification.sent_at = timezone.now()
    notification.save()
    logger.info("Statement emailed to tenant %s at %s", tenant.id, tenant.email)
    return notification
