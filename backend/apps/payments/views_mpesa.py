"""
M-Pesa Daraja C2B webhook views.

Two endpoints Safaricom calls on every payment:
  POST /api/payments/mpesa/validate/  — called BEFORE confirming
  POST /api/payments/mpesa/confirm/   — called AFTER money moves

Both must respond within 5 seconds or Safaricom times out and retries.
We accept/reject in validate; we record the payment in confirm.

Idempotency: TransID is stored as `reference` on Payment. A duplicate
TransID (replay) is silently accepted so Safaricom doesn't keep retrying.
"""
import logging
from decimal import Decimal

from django.utils import timezone
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.buildings.models import Unit
from apps.tenants.models import Tenant, TenantStatus

from .models import Payment, PaymentSource
from .mpesa import daraja
from .services import process_payment
from .tasks import send_payment_confirmation

logger = logging.getLogger(__name__)

MPESA_ACCEPT = {"ResultCode": 0, "ResultDesc": "Accepted"}
MPESA_REJECT = {"ResultCode": 1, "ResultDesc": "Rejected"}


def _get_client_ip(request: Request) -> str:
    x_forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded:
        return x_forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def _match_tenant(bill_ref: str) -> Tenant | None:
    """
    Match BillRefNumber (unit label, e.g. 'A1', 'B12') to the active tenant.
    Returns None if no active tenant found on that unit.
    """
    unit = Unit.objects.filter(label__iexact=bill_ref.strip()).first()
    if not unit:
        return None
    return Tenant.objects.filter(unit=unit, status=TenantStatus.ACTIVE).first()


class MpesaValidateView(APIView):
    """
    POST /api/payments/mpesa/validate/
    Safaricom calls this BEFORE debiting the customer.
    We accept if the unit exists and has an active tenant; reject otherwise.
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request: Request, *_args, **_kwargs) -> Response:
        ip = _get_client_ip(request)
        if not daraja.is_safaricom_ip(ip):
            logger.warning("M-Pesa validate: rejected non-Safaricom IP %s", ip)
            return Response(MPESA_REJECT)

        payload = request.data
        bill_ref = payload.get("BillRefNumber", "")
        trans_id = payload.get("TransID", "")
        amount_str = payload.get("TransAmount", "0")

        try:
            amount = Decimal(amount_str)
        except Exception:
            logger.warning("M-Pesa validate: invalid amount '%s'", amount_str)
            return Response(MPESA_REJECT)

        if amount <= 0:
            return Response(MPESA_REJECT)

        # Replay protection — if already processed, accept silently.
        if trans_id and Payment.objects.filter(reference=trans_id).exists():
            logger.info("M-Pesa validate: duplicate TransID %s — accepted silently", trans_id)
            return Response(MPESA_ACCEPT)

        tenant = _match_tenant(bill_ref)
        if not tenant:
            logger.warning("M-Pesa validate: no active tenant for BillRef '%s'", bill_ref)
            return Response(MPESA_REJECT)

        logger.info("M-Pesa validate: accepted %s for tenant %s", trans_id, tenant)
        return Response(MPESA_ACCEPT)


class MpesaConfirmView(APIView):
    """
    POST /api/payments/mpesa/confirm/
    Safaricom calls this AFTER money has moved. Record the payment here.
    Always return ACCEPT (200) so Safaricom doesn't retry endlessly.
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request: Request, *_args, **_kwargs) -> Response:
        ip = _get_client_ip(request)
        if not daraja.is_safaricom_ip(ip):
            logger.warning("M-Pesa confirm: rejected non-Safaricom IP %s", ip)
            return Response(MPESA_ACCEPT)  # Still 200 to prevent retries

        payload = request.data
        trans_id = payload.get("TransID", "")
        bill_ref = payload.get("BillRefNumber", "")
        amount_str = payload.get("TransAmount", "0")
        trans_time = payload.get("TransTime", "")  # YYYYMMDDHHmmss

        # Idempotency: if already recorded, return success immediately.
        if trans_id and Payment.objects.filter(reference=trans_id).exists():
            logger.info("M-Pesa confirm: duplicate TransID %s — skipped", trans_id)
            return Response(MPESA_ACCEPT)

        tenant = _match_tenant(bill_ref)
        if not tenant:
            logger.error("M-Pesa confirm: no tenant for BillRef '%s' TransID %s", bill_ref, trans_id)
            return Response(MPESA_ACCEPT)  # Accept so Safaricom stops retrying

        try:
            amount = Decimal(amount_str)
        except Exception:
            logger.error("M-Pesa confirm: invalid amount '%s'", amount_str)
            return Response(MPESA_ACCEPT)

        now = timezone.now()
        payment = process_payment(
            tenant=tenant,
            amount=amount,
            payment_date=now.date(),
            period_month=now.month,
            period_year=now.year,
            source=PaymentSource.MPESA,
            reference=trans_id,
            notes=f"M-Pesa C2B. TransTime: {trans_time}",
        )

        # Dispatch async tasks — fire and forget.
        send_payment_confirmation.delay(payment.id)
        logger.info("M-Pesa confirm: recorded payment %s KES %s", trans_id, amount)
        return Response(MPESA_ACCEPT)
