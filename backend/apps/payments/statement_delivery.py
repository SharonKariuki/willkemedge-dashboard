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
from contextlib import contextmanager

from django.conf import settings
from django.utils import timezone

from .models import NotificationChannel, NotificationStatus, TenantNotification

logger = logging.getLogger(__name__)


@contextmanager
def open_mail_connection():
    """One SMTP connection held open for a whole batch.

    Django opens and closes a connection per message by default. That is fine
    for a single receipt and is the slowest part of a statement run — the
    handshake dwarfs rendering the PDF — so a batch pays it once.

    Yields None when no credentials are configured, which is exactly what
    `send_email` expects for its own unconfigured path: it refuses to send
    before it ever touches the connection.
    """
    from django.core.mail import get_connection

    if not getattr(settings, "EMAIL_HOST_USER", "") or not getattr(
        settings, "EMAIL_HOST_PASSWORD", ""
    ):
        yield None
        return

    connection = get_connection()
    try:
        connection.open()
    except Exception as exc:
        # Not fatal: fall back to a connection per message, which may still get
        # through, and let each tenant record its own failure if it does not.
        logger.warning("Could not open a shared mail connection (%s) — sending one at a time", exc)
        yield None
        return

    try:
        yield connection
    finally:
        try:
            connection.close()
        except Exception:  # noqa: BLE001 - closing must never mask the batch result
            logger.debug("Ignoring error while closing the mail connection", exc_info=True)


def statement_dedupe_key(tenant_id: int, period) -> str:
    """Idempotency marker for the monthly run: one statement per tenant per month.

    ``period`` is a date inside the month the statement is *about*, which since
    the run moved to the 25th is not the month it was sent in — the September
    statement goes out in August and must key on September.

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
    period=None,
    automatic: bool = True,
    created_by=None,
    dedupe_key: str = "",
    connection=None,
) -> TenantNotification:
    """Email one tenant their rent statement with the PDF attached.

    Returns the `TenantNotification` recording the outcome — SENT, FAILED with
    the reason, or PENDING when an automatic send was suppressed. Never raises
    on a per-tenant problem (no email, no unit, SMTP refusal), so one bad row
    cannot abort a batch; the caller reads `status` to count what happened.

    `period` is the ``(year, month)`` the statement is about. It defaults to
    whatever month the billing cycle is on — from the 25th, next month — so a
    statement the office re-sends by hand is the same one the scheduled run
    emailed that morning, rather than the previous month's.

    `connection` is an open mail backend to send over, for batches that would
    otherwise pay an SMTP handshake per tenant; see `open_mail_connection`.

    `automatic` marks a send the system decided to make on its own — the monthly
    run. Those are what TENANT_NOTIFICATIONS_ENABLED silences. A manual send
    passes automatic=False: a person chose it and is watching the result, so it
    stays available while automatic messaging is paused. Same rule as
    `notification_services.dispatch_notification`.
    """
    from .billing_calendar import billing_period
    from .notifications import send_email, statement_email_html
    from .pdf_service import render_to_pdf
    from .statement_service import build_statement

    period = period or billing_period(statement_date)

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

    statement = build_statement(tenant, statement_date=statement_date, period=period)
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
            connection=connection,
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
