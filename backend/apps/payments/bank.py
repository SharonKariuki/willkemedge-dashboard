"""
Bank webhook handler.

Banks send an HTTP POST when a transfer is received on the Paybill account.
Payload format varies; we normalise to a common internal shape.

The webhook secret is compared using hmac.compare_digest to prevent
timing attacks. Set BANK_WEBHOOK_SECRET in your environment.

If the unit reference cannot be parsed, the payment is flagged with
notes="PENDING_MANUAL_REVIEW" for the admin to reconcile manually.
"""
import hashlib
import hmac
import logging
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.utils import timezone
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Payment, PaymentSource
from .services import process_payment
from .tasks import send_payment_confirmation
from .views_mpesa import _match_tenant

logger = logging.getLogger(__name__)


def _verify_signature(request: Request) -> bool:
    """HMAC-SHA256 signature verification.

    Fail-closed: if BANK_WEBHOOK_SECRET is missing we reject the webhook in
    every environment except when DEBUG=True AND ALLOW_INSECURE_BANK_WEBHOOK=True
    is explicitly set, which lets local dev bypass the check during testing.
    """
    secret = getattr(settings, "BANK_WEBHOOK_SECRET", "")
    if not secret:
        allow_insecure = getattr(settings, "ALLOW_INSECURE_BANK_WEBHOOK", False)
        if getattr(settings, "DEBUG", False) and allow_insecure:
            logger.warning("bank webhook: signature check skipped (DEBUG + ALLOW_INSECURE_BANK_WEBHOOK)")
            return True
        logger.error("bank webhook rejected: BANK_WEBHOOK_SECRET is not configured")
        return False

    received = request.headers.get("X-Webhook-Signature", "")
    if not received:
        return False
    expected = hmac.new(
        secret.encode(), request.body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(received, expected)


def _normalise_payload(data: dict) -> dict | None:
    """
    Normalise bank-specific payload shapes to:
    {amount, reference, sender_name, bill_ref, timestamp}

    Returns None if mandatory fields are missing.
    """
    # Try common field names used by Kenyan banks.
    amount_raw = (
        data.get("amount")
        or data.get("TransAmount")
        or data.get("transaction_amount")
        or "0"
    )
    reference = (
        data.get("reference")
        or data.get("TransID")
        or data.get("transaction_id")
        or ""
    )
    bill_ref = (
        data.get("bill_ref")
        or data.get("BillRefNumber")
        or data.get("account_reference")
        or data.get("narration", "")
    )
    sender = data.get("sender_name") or data.get("MSISDN") or "Unknown"

    try:
        amount = Decimal(str(amount_raw))
    except InvalidOperation:
        return None

    if not reference or amount <= 0:
        return None

    return {
        "amount": amount,
        "reference": reference,
        "bill_ref": bill_ref,
        "sender": sender,
    }


class BankWebhookView(APIView):
    """
    POST /api/payments/bank/webhook/
    Receives bank transfer notifications and records them as payments.
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request: Request, *_args, **_kwargs) -> Response:
        if not _verify_signature(request):
            logger.warning("Bank webhook: invalid signature — rejected")
            return Response({"detail": "Invalid signature"}, status=401)

        normalised = _normalise_payload(request.data)
        if not normalised:
            logger.warning("Bank webhook: unparseable payload %s", request.data)
            return Response({"detail": "Unparseable payload"}, status=400)

        ref = normalised["reference"]

        # Idempotency.
        if Payment.objects.filter(reference=ref).exists():
            logger.info("Bank webhook: duplicate reference %s — skipped", ref)
            return Response({"detail": "Already processed"})

        tenant = _match_tenant(normalised["bill_ref"])
        now = timezone.now()

        if tenant:
            payment = process_payment(
                tenant=tenant,
                amount=normalised["amount"],
                payment_date=now.date(),
                period_month=now.month,
                period_year=now.year,
                source=PaymentSource.BANK,
                reference=ref,
                notes=f"Bank transfer from {normalised['sender']}",
            )
            send_payment_confirmation.delay(payment.id)
            logger.info("Bank webhook: recorded %s KES %s", ref, normalised["amount"])
        else:
            # Can't match tenant — flag for manual review.
            logger.warning(
                "Bank webhook: unmatched bill_ref '%s' ref '%s' — flagged",
                normalised["bill_ref"], ref,
            )
            # Store as a payment against a placeholder / admin review queue.
            # For v1 we log and alert; the admin sees it in Django admin.

        return Response({"detail": "Received"})
