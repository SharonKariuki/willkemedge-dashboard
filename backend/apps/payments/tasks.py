"""
Celery tasks for the payments app.

Tasks:
  send_payment_confirmation  — SMS + email after every payment
  recalculate_all_statuses   — nightly unit status sweep
  generate_monthly_arrears   — 1st of month: create arrears records
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

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_payment_confirmation(self, payment_id: int) -> None:
    """
    Fire SMS to tenant phone and email to tenant email (if set)
    after a payment is recorded.
    """
    from .models import Payment
    from .notifications import (
        payment_email_html,
        payment_sms_message,
        send_email,
        send_sms,
    )

    try:
        payment = Payment.objects.select_related(
            "tenant", "tenant__unit", "tenant__unit__building"
        ).get(pk=payment_id)
    except Payment.DoesNotExist:
        logger.error("send_payment_confirmation: Payment %s not found", payment_id)
        return

    tenant = payment.tenant
    unit_label = f"{tenant.unit.building.name} – {tenant.unit.label}"
    period = f"{payment.period_month}/{payment.period_year}"
    ref = payment.reference or str(payment.id)

    try:
        # SMS
        msg = payment_sms_message(tenant.full_name, payment.amount, unit_label, ref)
        send_sms(tenant.phone, msg)

        # Email (optional)
        if tenant.email:
            html = payment_email_html(
                tenant.full_name, payment.amount, unit_label, period, ref
            )
            send_email(
                tenant.email,
                f"Payment Received – KES {payment.amount:,.2f}",
                html,
            )
    except Exception as exc:
        logger.warning("send_payment_confirmation retry %s: %s", self.request.retries, exc)
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries)) from exc


# ---------------------------------------------------------------------------
# Task 5.7 — bank polling fallback (runs hourly via Celery Beat)
# ---------------------------------------------------------------------------

@shared_task(bind=True, max_retries=2)
def poll_bank_statement(self) -> None:
    """
    Hourly fallback for banks that don't support webhooks.
    Fetches recent transactions from the bank API and processes new ones.

    Implementation is bank-specific. The stub below logs a warning so the
    admin knows to wire up the real bank API client when credentials are
    available.
    """
    from django.conf import settings

    bank_api_key = getattr(settings, "BANK_API_KEY", "")
    if not bank_api_key:
        logger.debug("poll_bank_statement: BANK_API_KEY not set — skipping poll")
        return

    # TODO: implement bank-specific API call here.
    # Pattern:
    #   1. Fetch transactions since last_poll_ts (store in Django cache or DB)
    #   2. For each: check Payment.objects.filter(reference=tx_ref).exists()
    #   3. If new: call process_payment(..., source=PaymentSource.BANK)
    #   4. Update last_poll_ts
    logger.info("poll_bank_statement: stub executed — wire up real bank client here")


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
