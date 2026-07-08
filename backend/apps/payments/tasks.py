"""
Celery tasks for the payments app.

Tasks:
  send_payment_confirmation  — SMS + email after every payment
  recalculate_all_statuses   — nightly unit status sweep
  generate_monthly_arrears   — 1st of month: create arrears records
  send_rent_reminders        — daily: SMS N days before each tenant's due day
  send_arrears_reminders     — daily: SMS on/after due day when rent unpaid
  poll_bank_statement        — hourly fallback for banks without webhooks

All tasks use bind=True + max_retries=3 with exponential backoff.
"""
import logging

from celery import shared_task
from django.db import models
from django.utils import timezone

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Task 5.8 / 5.9 — payment confirmation (SMS + email)
# ---------------------------------------------------------------------------

def _notify_tenant_payment(tenant, amount, reference: str, payment_date) -> None:
    """Send the tenant an SMS + (if they have email) a rent-statement email.

    Shared by send_payment_confirmation (per-Payment) and send_deposit_receipt
    (per-deposit total, so a FIFO-split credit produces ONE receipt for the full
    amount rather than one per period chunk). Raises on failure so the caller
    can retry.
    """
    from .notifications import (
        payment_sms_message,
        payment_statement_email_html,
        send_email,
        send_sms,
    )
    from .pdf_service import render_to_pdf
    from .statement_service import build_statement

    unit_label = f"{tenant.unit.building.name} – {tenant.unit.label}"

    # Build the statement once — the SMS now carries the same five named totals
    # as the email receipt, so both channels agree.
    statement = build_statement(tenant, statement_date=payment_date, as_of=payment_date)

    msg = payment_sms_message(tenant.full_name, amount, unit_label, reference, statement)
    send_sms(tenant.phone, msg)

    if tenant.email:
        html = payment_statement_email_html(tenant.full_name, amount, reference, statement)
        attachments = []
        pdf = render_to_pdf("payments/statement_pdf.html", statement)
        if pdf:
            safe_name = tenant.full_name.replace(" ", "_")
            attachments.append((f"Rent_Statement_{safe_name}.pdf", pdf, "application/pdf"))
        send_email(
            tenant.email,
            f"Rent Statement – {tenant.unit.building.name} {tenant.unit.label}",
            html,
            attachments=attachments,
        )


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_payment_confirmation(self, payment_id: int) -> None:
    """Fire SMS + email to the tenant after a single payment is recorded."""
    from .models import Payment

    try:
        payment = Payment.objects.select_related(
            "tenant", "tenant__unit", "tenant__unit__building"
        ).get(pk=payment_id)
    except Payment.DoesNotExist:
        logger.error("send_payment_confirmation: Payment %s not found", payment_id)
        return

    ref = payment.reference or str(payment.id)
    try:
        _notify_tenant_payment(payment.tenant, payment.amount, ref, payment.payment_date)
    except Exception as exc:
        logger.warning("send_payment_confirmation retry %s: %s", self.request.retries, exc)
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries)) from exc


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_deposit_receipt(self, tenant_id: int, amount: str, reference: str, payment_date: str) -> None:
    """One tenant receipt for a full deposit (used by the IPN path, where a
    credit may be FIFO-split across several periods). `amount` is the total
    received; `payment_date` is an ISO date string."""
    import datetime as _dt
    from decimal import Decimal

    from apps.tenants.models import Tenant

    try:
        tenant = Tenant.objects.select_related("unit", "unit__building").get(pk=tenant_id)
    except Tenant.DoesNotExist:
        logger.error("send_deposit_receipt: Tenant %s not found", tenant_id)
        return

    try:
        pay_date = _dt.date.fromisoformat(payment_date[:10])
    except (ValueError, TypeError):
        pay_date = timezone.now().date()

    try:
        _notify_tenant_payment(tenant, Decimal(str(amount)), reference, pay_date)
    except Exception as exc:
        logger.warning("send_deposit_receipt retry %s: %s", self.request.retries, exc)
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries)) from exc


@shared_task(bind=True, max_retries=3, default_retry_delay=120)
def send_unmatched_credit_alert(self, event_id: int) -> None:
    """Alert the admin (SMS + email) when an IPN credit can't be auto-assigned
    and needs manual reconciliation (review item M1)."""
    from django.conf import settings

    from .models import CoopIpnEvent
    from .notifications import custom_email_html, send_email, send_sms

    try:
        event = CoopIpnEvent.objects.get(pk=event_id)
    except CoopIpnEvent.DoesNotExist:
        logger.error("send_unmatched_credit_alert: event %s not found", event_id)
        return

    phone = getattr(settings, "ADMIN_ALERT_PHONE", "")
    email = getattr(settings, "ADMIN_ALERT_EMAIL", "")
    if not phone and not email:
        logger.warning("send_unmatched_credit_alert: no ADMIN_ALERT_PHONE/EMAIL set — alert skipped")
        return

    sms_text = (
        f"Wilkem Edge: unmatched payment KES {event.amount} (ref {event.transaction_id}). "
        f"Reason: {event.detail}. Please reconcile in the dashboard."
    )
    email_body = (
        "A bank credit could not be automatically assigned to a tenant and needs review.\n\n"
        f"Amount: KES {event.amount}\n"
        f"Transaction ID: {event.transaction_id}\n"
        f"Payment Ref: {event.payment_ref}\n"
        f"Account: {event.account_number}\n"
        f"Reason: {event.detail}\n\n"
        f"Narration: {event.narration}\n\n"
        "Open the dashboard (Admin → Co-op IPN events, filter Unmatched) to assign it."
    )
    try:
        if phone:
            send_sms(phone, sms_text)
        if email:
            send_email(email, "Action needed: unmatched bank credit", custom_email_html(
                "Unmatched bank credit", email_body))
    except Exception as exc:
        logger.warning("send_unmatched_credit_alert retry %s: %s", self.request.retries, exc)
        raise self.retry(exc=exc, countdown=120 * (2 ** self.request.retries)) from exc


@shared_task(bind=True, max_retries=2, default_retry_delay=300)
def send_daily_reconciliation(self, target_iso: str | None = None) -> None:
    """One-page summary of yesterday's IPN events emailed (and SMSed) to the
    admin + director. Wire up nightly via Render Cron Job or Celery Beat.

    `target_iso` (YYYY-MM-DD) lets the caller backfill a specific day; default
    is yesterday in the project timezone."""
    import datetime as _dt

    from django.conf import settings

    from .notifications import custom_email_html, send_email, send_sms
    from .reconciliation import (
        build_daily_reconciliation_summary,
        render_summary_sms,
        render_summary_text,
    )

    target = None
    if target_iso:
        try:
            target = _dt.date.fromisoformat(target_iso)
        except ValueError:
            logger.warning("send_daily_reconciliation: bad target_iso=%r — using yesterday", target_iso)

    summary = build_daily_reconciliation_summary(target)
    body = render_summary_text(summary)
    sms = render_summary_sms(summary)

    emails = {
        e for e in (
            getattr(settings, "ADMIN_ALERT_EMAIL", ""),
            getattr(settings, "DIRECTOR_ALERT_EMAIL", ""),
        ) if e
    }
    phones = {
        p for p in (
            getattr(settings, "ADMIN_ALERT_PHONE", ""),
            getattr(settings, "DIRECTOR_ALERT_PHONE", ""),
        ) if p
    }
    if not emails and not phones:
        logger.warning("send_daily_reconciliation: no recipients configured — skipping")
        return

    subject = f"Wilkem Edge — rent collections summary, {summary['date']}"
    html = custom_email_html(subject, body)

    try:
        for email in emails:
            send_email(email, subject, html)
        for phone in phones:
            send_sms(phone, sms)
    except Exception as exc:
        logger.warning("send_daily_reconciliation retry %s: %s", self.request.retries, exc)
        raise self.retry(exc=exc, countdown=300 * (2 ** self.request.retries)) from exc


@shared_task(bind=True, max_retries=3, default_retry_delay=120)
def send_reversal_authorization_alert(self, event_id: int) -> None:
    """Alert the authorising director (Dr. Osoro) that the bank has notified a
    reversal, which must be authorized before any tenant payment is undone.

    Recipients: DIRECTOR_ALERT_PHONE / DIRECTOR_ALERT_EMAIL, falling back to the
    ADMIN_ALERT_* values so the alert always reaches someone."""
    from django.conf import settings

    from .models import CoopIpnEvent
    from .notifications import custom_email_html, send_email, send_sms

    try:
        event = CoopIpnEvent.objects.get(pk=event_id)
    except CoopIpnEvent.DoesNotExist:
        logger.error("send_reversal_authorization_alert: event %s not found", event_id)
        return

    phone = getattr(settings, "DIRECTOR_ALERT_PHONE", "") or getattr(settings, "ADMIN_ALERT_PHONE", "")
    email = getattr(settings, "DIRECTOR_ALERT_EMAIL", "") or getattr(settings, "ADMIN_ALERT_EMAIL", "")
    if not phone and not email:
        logger.warning("send_reversal_authorization_alert: no director/admin contact set — alert skipped")
        return

    sms_text = (
        f"Wilkem Edge: bank REVERSAL of KES {event.amount} (ref {event.transaction_id}) "
        f"requires your authorization. No tenant payment has been undone. "
        f"Please review in the dashboard."
    )
    email_body = (
        "The bank has notified a REVERSAL on the collection account. It has NOT been "
        "applied — a tenant's recorded payment will only be undone after you authorize it.\n\n"
        f"Amount: KES {event.amount}\n"
        f"Transaction ID: {event.transaction_id}\n"
        f"Payment Ref: {event.payment_ref}\n"
        f"Account: {event.account_number}\n"
        f"Detail: {event.detail}\n\n"
        f"Narration: {event.narration}\n\n"
        "To authorize: open the dashboard (Admin → Co-op IPN events, filter "
        "'Reversal — awaiting authorization') and confirm the reversal."
    )
    try:
        if phone:
            send_sms(phone, sms_text)
        if email:
            send_email(email, "AUTHORIZATION NEEDED: bank reversal", custom_email_html(
                "Bank reversal — authorization required", email_body))
    except Exception as exc:
        logger.warning("send_reversal_authorization_alert retry %s: %s", self.request.retries, exc)
        raise self.retry(exc=exc, countdown=120 * (2 ** self.request.retries)) from exc


# ---------------------------------------------------------------------------
# Task 5.7 — bank polling fallback (runs hourly via Celery Beat)
# ---------------------------------------------------------------------------

@shared_task(bind=True, max_retries=2)
def poll_bank_statement(self) -> None:
    """
    Backfill safety net for the Co-op IPN feed (review item M4).

    IPN has no replay once Co-op's delivery retries are exhausted, so if the
    endpoint is down past their window those credits are lost. This task is the
    intended fallback: poll Co-op Connect `/Enquiry/AccountTransactions/1.0.0`
    and reconcile any credit not already captured as a CoopIpnEvent.

    Stub for now — needs Co-op Connect OAuth credentials (separate enrolment
    from IPN). Skips quietly until those are configured.
    """
    from django.conf import settings

    consumer_key = getattr(settings, "COOP_CONNECT_CONSUMER_KEY", "")
    if not consumer_key:
        logger.debug("poll_bank_statement: Co-op Connect not configured — skipping backfill")
        return

    # TODO (Phase 3): implement Co-op Connect AccountTransactions backfill.
    # Pattern:
    #   1. OAuth client_credentials → bearer token
    #   2. Fetch transactions since last_poll_ts (store in cache/DB)
    #   3. For each credit: skip if CoopIpnEvent.objects.filter(transaction_id=ref).exists()
    #   4. Else reconcile via the same path as CoopIpnView
    #   5. Update last_poll_ts
    logger.info("poll_bank_statement: stub executed — wire up Co-op Connect client here")


# ---------------------------------------------------------------------------
# Nightly jobs — unit status sweep + monthly arrears
# ---------------------------------------------------------------------------

@shared_task
def recalculate_all_statuses() -> None:
    """
    Nightly at 00:30 EAT. Recalculate every occupied unit's status
    based on current-month payments to catch anything missed intraday.
    """
    from decimal import Decimal

    from apps.buildings.models import Unit, UnitStatus
    from apps.buildings.services import recalculate_unit_status
    from apps.tenants.models import Tenant, TenantStatus

    from .models import Payment

    now = timezone.now()
    occupied = Unit.objects.exclude(status=UnitStatus.VACANT)
    updated = 0

    for unit in occupied:
        tenant = Tenant.objects.filter(unit=unit, status=TenantStatus.ACTIVE).first()
        if not tenant:
            unit.status = UnitStatus.VACANT
            unit.save(update_fields=["status", "updated_at"])
            updated += 1
            continue

        total_paid = Payment.objects.filter(
            tenant=tenant,
            period_month=now.month,
            period_year=now.year,
        ).aggregate(total=models.Sum("amount"))["total"] or Decimal("0")

        recalculate_unit_status(unit, total_paid)
        updated += 1

    logger.info("recalculate_all_statuses: updated %d units", updated)


@shared_task
def generate_monthly_arrears() -> None:
    """
    Runs on the 1st of each month at 00:05 EAT.
    Creates an Arrears record for every active tenant if one doesn't exist yet.
    """
    from apps.tenants.models import Tenant, TenantStatus

    from .models import Arrears

    now = timezone.now()
    active = Tenant.objects.filter(status=TenantStatus.ACTIVE)
    created = 0

    for tenant in active:
        _, was_created = Arrears.objects.get_or_create(
            tenant=tenant,
            period_month=now.month,
            period_year=now.year,
            defaults={
                "expected_rent": tenant.monthly_rent,
                "amount_paid": 0,
                "balance": tenant.monthly_rent,
                "is_cleared": False,
            },
        )
        if was_created:
            created += 1

    logger.info("generate_monthly_arrears: created %d new arrears records", created)


# ---------------------------------------------------------------------------
# Rent reminders (Feature 5) — SMS N days before each tenant's due day
# ---------------------------------------------------------------------------

@shared_task
def send_rent_reminders() -> int:
    """
    Daily at 08:00 EAT. Send each active tenant a rent-reminder SMS when their
    rent due date is within RENT_REMINDER_LEAD_DAYS days.

    Idempotent: one reminder per tenant per period, keyed by dedupe_key, so
    re-running the job (or a missed-then-recovered scheduler) never double-sends.
    The Africa's Talking delivery receipt is persisted on the notification by
    dispatch_notification.
    """
    import calendar
    from datetime import date

    from django.conf import settings

    from apps.tenants.models import Tenant, TenantStatus

    from .models import NotificationChannel, NotificationStatus, TenantNotification
    from .notification_services import dispatch_notification
    from .notification_templates import get_template

    lead_days = int(getattr(settings, "RENT_REMINDER_LEAD_DAYS", 3))
    today = timezone.localdate()
    last_day = calendar.monthrange(today.year, today.month)[1]
    template = get_template("rent_reminder")
    sent = 0

    active = Tenant.objects.filter(status=TenantStatus.ACTIVE).select_related(
        "unit", "unit__building"
    )
    for tenant in active:
        if not tenant.unit_id or not tenant.phone:
            continue
        # Clamp the due day to the current month's length (e.g. 31 → 30 / 28).
        due_day = min(int(tenant.due_day or 5), last_day)
        due_date = date(today.year, today.month, due_day)
        days_until = (due_date - today).days
        if not 0 <= days_until <= lead_days:
            continue

        dedupe_key = f"rent_reminder:{tenant.id}:{due_date:%Y-%m}"
        if TenantNotification.objects.filter(dedupe_key=dedupe_key).exists():
            continue

        notification = TenantNotification.objects.create(
            tenant=tenant,
            channel=NotificationChannel.SMS,
            subject=template["subject"],
            body=template["body"],
            template_key="rent_reminder",
            dedupe_key=dedupe_key,
            status=NotificationStatus.PENDING,
        )
        dispatch_notification(notification)
        notification.refresh_from_db()
        if notification.status == NotificationStatus.SENT:
            sent += 1

    logger.info("send_rent_reminders: sent %d reminders (lead=%d days)", sent, lead_days)
    return sent


# ---------------------------------------------------------------------------
# Arrears reminders (Feature 6) — SMS on/after due day when rent is unpaid
# ---------------------------------------------------------------------------

@shared_task
def send_arrears_reminders() -> int:
    """
    Daily at 09:00 EAT. Send an overdue-rent SMS to each active tenant whose
    rent for the current period is still unpaid once their due day has passed.

    Unpaid is sourced from the canonical Arrears row for the current period
    (so the figure matches the tenant statement). One reminder per tenant per
    period via dedupe_key — re-running the job never double-sends.
    """
    import calendar
    from datetime import date

    from apps.tenants.models import Tenant, TenantStatus

    from .models import (
        Arrears,
        NotificationChannel,
        NotificationStatus,
        TenantNotification,
    )
    from .notification_services import dispatch_notification
    from .notification_templates import get_template

    today = timezone.localdate()
    last_day = calendar.monthrange(today.year, today.month)[1]
    template = get_template("rent_overdue")
    sent = 0

    active = Tenant.objects.filter(status=TenantStatus.ACTIVE).select_related(
        "unit", "unit__building"
    )
    for tenant in active:
        if not tenant.unit_id or not tenant.phone:
            continue
        due_day = min(int(tenant.due_day or 5), last_day)
        due_date = date(today.year, today.month, due_day)
        if today < due_date:
            continue  # rent not due yet this period

        arrears = Arrears.objects.filter(
            tenant=tenant,
            period_month=today.month,
            period_year=today.year,
            is_cleared=False,
        ).first()
        if not arrears or arrears.balance <= 0:
            continue  # nothing outstanding for the current period

        dedupe_key = f"rent_overdue:{tenant.id}:{due_date:%Y-%m}"
        if TenantNotification.objects.filter(dedupe_key=dedupe_key).exists():
            continue

        notification = TenantNotification.objects.create(
            tenant=tenant,
            channel=NotificationChannel.SMS,
            subject=template["subject"],
            body=template["body"],
            template_key="rent_overdue",
            dedupe_key=dedupe_key,
            status=NotificationStatus.PENDING,
        )
        dispatch_notification(notification)
        notification.refresh_from_db()
        if notification.status == NotificationStatus.SENT:
            sent += 1

    logger.info("send_arrears_reminders: sent %d arrears reminders", sent)
    return sent
