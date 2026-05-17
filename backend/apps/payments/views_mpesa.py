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
import re
from decimal import Decimal

from django.conf import settings
from django.utils import timezone
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
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

# Separators a tenant might type between the account prefix and the house
# number (e.g. "90290#A12", "90290 A12", "90290-A12").
_BILL_REF_SEP_RE = re.compile(r"^[\s#*\-./]+")


def _get_client_ip(request: Request) -> str:
    x_forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded:
        return x_forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


class MpesaWebhookThrottle(SimpleRateThrottle):
    """Per-IP throttle for the M-Pesa C2B endpoints.

    Safaricom retries timed-out webhooks, but legitimate traffic for a
    single shortcode tops out at a few requests per second. 60/minute per
    IP is comfortably above legitimate volume and an order of magnitude
    below what an attacker would need to spam payments / notifications.
    """
    scope = "mpesa_webhook"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": _get_client_ip(request)}


def _normalize_bill_ref(bill_ref: str) -> str:
    """
    Recover the bare house number from a paybill BillRefNumber.

    Tenants pay paybill <MPESA_SHORTCODE> with account "<prefix>#<house number>"
    (e.g. "90290#A12"), so Safaricom forwards "90290#A12" — or with a space,
    dash, or no separator at all. Strip the configured MPESA_ACCOUNT_PREFIX and
    any leading separator so what's left can be matched against Unit.label.
    A tenant who typed just the house number ("A12") still works.
    """
    ref = (bill_ref or "").strip().upper()
    prefix = str(getattr(settings, "MPESA_ACCOUNT_PREFIX", "") or "").strip().upper()
    if prefix and ref.startswith(prefix):
        ref = ref[len(prefix):]
    return _BILL_REF_SEP_RE.sub("", ref).strip()


def _match_tenant(bill_ref: str) -> Tenant | None:
    """
    Match BillRefNumber to the active tenant on the referenced unit.
    BillRefNumber is normalized first (prefix stripped) to a bare house
    number, e.g. 'A1' / 'B12'. Returns None if no active tenant is found.
    """
    house_number = _normalize_bill_ref(bill_ref)
    if not house_number:
        return None
    unit = Unit.objects.filter(label__iexact=house_number).first()
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
    throttle_classes = [MpesaWebhookThrottle]

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
    throttle_classes = [MpesaWebhookThrottle]

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


def _normalize_msisdn(phone: str | int) -> str:
    """Reduce any Kenyan phone format to bare digits starting with 254."""
    digits = "".join(c for c in str(phone) if c.isdigit())
    if digits.startswith("0"):
        digits = "254" + digits[1:]
    return digits


def _tenant_by_phone(msisdn: str) -> Tenant | None:
    """Find the active tenant whose stored phone matches the M-Pesa MSISDN."""
    target = _normalize_msisdn(msisdn)
    for tenant in Tenant.objects.filter(status=TenantStatus.ACTIVE):
        if _normalize_msisdn(tenant.phone) == target:
            return tenant
    return None


class MpesaStkCallbackView(APIView):
    """
    POST /api/payments/mpesa/stk-callback/
    Safaricom posts the result of an STK Push (Lipa Na M-Pesa Online) here.

    Payload (success):
        {"Body": {"stkCallback": {
            "MerchantRequestID": "...",
            "CheckoutRequestID": "ws_CO_...",
            "ResultCode": 0,
            "CallbackMetadata": {"Item": [
                {"Name": "Amount", "Value": 100.0},
                {"Name": "MpesaReceiptNumber", "Value": "ABC123XYZ"},
                {"Name": "PhoneNumber", "Value": 254708374149},
                ...
            ]}
        }}}

    On failure ResultCode != 0 and CallbackMetadata is absent (e.g. user
    cancelled, insufficient funds, timeout). We log and return 200 either way
    so Safaricom doesn't keep retrying.
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request: Request, *_args, **_kwargs) -> Response:
        ip = _get_client_ip(request)
        if not daraja.is_safaricom_ip(ip):
            logger.warning("STK callback: rejected non-Safaricom IP %s", ip)
            return Response(MPESA_ACCEPT)  # 200 to avoid retries from spoofed IPs

        body = (request.data or {}).get("Body", {}).get("stkCallback", {}) or {}
        result_code = body.get("ResultCode")
        checkout_id = body.get("CheckoutRequestID", "")
        result_desc = body.get("ResultDesc", "")

        if result_code != 0:
            logger.info(
                "STK callback: payment NOT completed — CheckoutRequestID=%s code=%s desc=%s",
                checkout_id, result_code, result_desc,
            )
            return Response(MPESA_ACCEPT)

        items = {
            i.get("Name"): i.get("Value")
            for i in body.get("CallbackMetadata", {}).get("Item", [])
        }
        receipt = str(items.get("MpesaReceiptNumber", "")).strip()
        amount_raw = items.get("Amount")
        phone_raw = items.get("PhoneNumber", "")

        if not receipt or amount_raw is None:
            logger.error("STK callback: missing receipt or amount in payload: %s", items)
            return Response(MPESA_ACCEPT)

        # Idempotency — Safaricom can retry the callback.
        if Payment.objects.filter(reference=receipt).exists():
            logger.info("STK callback: duplicate receipt %s — skipped", receipt)
            return Response(MPESA_ACCEPT)

        tenant = _tenant_by_phone(phone_raw)
        if not tenant:
            logger.error(
                "STK callback: no active tenant matches phone %s (receipt %s)",
                phone_raw, receipt,
            )
            return Response(MPESA_ACCEPT)

        try:
            amount = Decimal(str(amount_raw))
        except Exception:
            logger.error("STK callback: invalid amount '%s'", amount_raw)
            return Response(MPESA_ACCEPT)

        now = timezone.now()
        payment = process_payment(
            tenant=tenant,
            amount=amount,
            payment_date=now.date(),
            period_month=now.month,
            period_year=now.year,
            source=PaymentSource.MPESA,
            reference=receipt,
            notes=f"M-Pesa STK Push. CheckoutRequestID: {checkout_id}",
        )

        send_payment_confirmation.delay(payment.id)
        logger.info("STK callback: recorded payment %s KES %s", receipt, amount)
        return Response(MPESA_ACCEPT)
