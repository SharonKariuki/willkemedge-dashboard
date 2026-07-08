"""
Co-operative Bank IPN (Instant Payment Notification) receiver.

Co-op posts an HTTP POST to this endpoint for every credit entry on the
institution account behind Paybill 400222 — both M-Pesa collections and direct
bank deposits. We record matched credits as Payments and queue anything we
can't tie to a tenant for manual review. See `B2B IPN_2025.pdf` / the CBS Event
Notification spec for the payload shape.

Safety properties (see review C1–C4, H1/H3/H5)
----------------------------------------------
* **Source-IP allowlist** (COOP_IPN_ALLOWED_IPS, single IPs or CIDR ranges)
  checked first: a request from outside Co-op's range is rejected with 403
  before the token is even examined. Spoof-resistant — the client IP is taken
  from the trusted-proxy position in X-Forwarded-For, not the leftmost
  (client-supplied) entry. Empty allowlist = allow all until Co-op shares it.
* **Bearer-token auth**, timing-safe, fail-closed (401 on missing/invalid).
* **Per-IP throttle** so retry storms / brute-force can't overwhelm the endpoint.
* **Atomic idempotency:** the unique `TransactionId` is *claimed* by creating the
  CoopIpnEvent row inside the same transaction as the Payment. A concurrent or
  replayed delivery hits the unique constraint (IntegrityError) and is acked
  without a second Payment. An unexpected error rolls the whole thing back so
  the bank's retry reprocesses cleanly — no orphaned Payment, no lost credit.
* **Account guard:** credits whose AcctNo != COOP_ACCOUNT_NUMBER are ignored.
* **Strict CREDIT:** only EventType == "CREDIT" is booked; everything else
  (DEBIT, reversals, or a missing field) is ignored, never assumed income.
* **Response:** the spec requires `{"MessageCode","Message"}`. 200/201 = received;
  any other code makes Co-op re-deliver up to a max then give up. After auth we
  return 200 for every terminal outcome (recorded / ignored / unmatched) so a
  payload we merely can't match is never lost to exhausted retries.
* **PII:** payer name/phone are NOT written to logs (Data Protection Act 2019).

KNOWN UNKNOWN: the exact position of the tenant's bill reference inside the real
M-Pesa narration for THIS paybill is confirmed only from Co-op's Postman test.
The parser extracts the spec sample's layout and falls back to payer phone;
anything it can't confidently match is queued UNMATCHED with the raw payload
kept, so the parser can be refined and history re-processed without data loss.
"""
import datetime as dt
import hmac
import ipaddress
import logging
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.conf import settings
from django.db import IntegrityError
from django.db import transaction as db_transaction
from django.utils import timezone
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

from .matching import match_tenant, tenant_by_name, tenant_by_phone
from .models import CoopIpnEvent, CoopIpnStatus, PaymentSource
from .services import allocate_payment_fifo
from .tasks import (
    send_deposit_receipt,
    send_reversal_authorization_alert,
    send_unmatched_credit_alert,
)

logger = logging.getLogger(__name__)

# Spec response bodies (CBS Event Notification spec, §4.3).
IPN_OK = {"MessageCode": "200", "Message": "Successfully received data"}


def _ipn_error(message: str) -> dict:
    return {"MessageCode": "400", "Message": message}


def _client_ip(request: Request) -> str:
    """Resolve the originating client IP, safe to use for an allowlist.

    `X-Forwarded-For` is "client, proxy1, proxy2, …": each proxy appends the IP
    it received the request FROM. A client can prepend a forged value, so the
    *leftmost* entry is spoofable and must never be trusted for access control.
    With N trusted proxies in front of the app (Render runs one edge proxy by
    default), the real client IP is the Nth entry from the right. Anything
    further left is client-supplied. When no proxy is trusted, or X-F-F is
    absent, fall back to REMOTE_ADDR (the immediate peer).
    """
    num_proxies = getattr(settings, "COOP_IPN_TRUSTED_PROXY_COUNT", 1)
    if num_proxies > 0:
        fwd = request.META.get("HTTP_X_FORWARDED_FOR", "")
        parts = [p.strip() for p in fwd.split(",") if p.strip()]
        if parts:
            idx = len(parts) - num_proxies
            return parts[idx] if idx >= 0 else parts[0]
    return request.META.get("REMOTE_ADDR", "")


def _mask_phone(phone: str) -> str:
    """Mask a phone for logging — keep last 3 digits only (DPA 2019)."""
    digits = "".join(c for c in str(phone) if c.isdigit())
    return f"***{digits[-3:]}" if len(digits) >= 3 else "***"


class CoopIpnThrottle(SimpleRateThrottle):
    """Per-IP throttle for the IPN endpoint. Comfortably above legitimate
    bank volume, well below what a brute-force/flood would need."""
    scope = "coop_ipn"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": _client_ip(request)}


def _bearer_token_ok(request: Request) -> bool:
    """Validate `Authorization: Bearer <token>` against COOP_IPN_TOKEN.

    Fail-closed: a missing COOP_IPN_TOKEN rejects every request, except when
    DEBUG=True AND ALLOW_INSECURE_COOP_IPN=True (local dev only).
    """
    expected = getattr(settings, "COOP_IPN_TOKEN", "")
    if not expected:
        if getattr(settings, "DEBUG", False) and getattr(settings, "ALLOW_INSECURE_COOP_IPN", False):
            logger.warning("Co-op IPN: auth skipped (DEBUG + ALLOW_INSECURE_COOP_IPN)")
            return True
        logger.error("Co-op IPN rejected: COOP_IPN_TOKEN is not configured")
        return False
    header = request.headers.get("Authorization", "")
    prefix = "Bearer "
    if not header.startswith(prefix):
        return False
    return hmac.compare_digest(header[len(prefix):].strip(), expected)


def _ip_allowed(request: Request) -> bool:
    """Source-IP allowlist. Empty COOP_IPN_ALLOWED_IPS == allow all (until Co-op
    shares their range). Entries may be single IPs (`196.201.214.200`) or CIDR
    ranges (`196.201.214.0/24`); a bank typically posts from a subnet.

    Fail-closed: once an allowlist is configured, an unparseable client IP is
    denied rather than waved through."""
    allowed = [e.strip() for e in getattr(settings, "COOP_IPN_ALLOWED_IPS", []) if e.strip()]
    if not allowed:
        return True
    try:
        client = ipaddress.ip_address(_client_ip(request))
    except ValueError:
        logger.warning("Co-op IPN: client IP %r unparseable — denied", _client_ip(request))
        return False
    for entry in allowed:
        try:
            if "/" in entry:
                if client in ipaddress.ip_network(entry, strict=False):
                    return True
            elif client == ipaddress.ip_address(entry):
                return True
        except ValueError:
            logger.error("Co-op IPN: invalid COOP_IPN_ALLOWED_IPS entry %r — skipped", entry)
            continue
    return False


def _posting_date(payload: dict) -> dt.date:
    """Booking date from the bank's PostingDate (fallback ValueDate, then now).

    The credit must be booked to the date the BANK posted it, never the server's
    receive time — otherwise a payment made on the 1st of next month lands in the
    wrong period (review C2)."""
    for key in ("PostingDate", "ValueDate", "TransactionDate"):
        raw = str(payload.get(key, "")).strip()
        if raw:
            try:
                return dt.date.fromisoformat(raw[:10])
            except ValueError:
                continue
    return timezone.now().date()


def _parse_narration(narration: str) -> dict:
    """Extract payer details + channel from the tilde-delimited narration.

    Real M-Pesa C2B format observed from Co-op IPN on Paybill 400222:
        UF7HG6UZBO~90290#A12~254726012481~MPESAC2B_400222~HUSSEIN HAMISI
        (code)    ~(bill ref)~(payer phone)~(channel + paybill)~(payer name)

    Earlier spec sample had positions 1 and 2 swapped (phone first, then
    account). Both layouts work: we scan positions 1 and 2 for whichever one
    looks like a Kenyan MSISDN (12 digits starting with 254) and take that as
    the payer phone. Bill ref candidates are surfaced via `tokens` and tried
    by `_resolve_tenant` in narration order.

    Missing pieces come back empty; the caller decides how to match.
    """
    parts = [p.strip() for p in (narration or "").split("~")]
    upper = (narration or "").upper()
    payer_phone = ""
    payer_name = ""
    if "MPESAC2B" in upper:
        channel = PaymentSource.MPESA
        # phone at position 1 or 2 (whichever looks like a Kenyan MSISDN)
        for candidate in parts[1:3]:
            if candidate.isdigit() and candidate.startswith("254") and len(candidate) == 12:
                payer_phone = candidate
                break
        # M-Pesa C2B narration: payer name is the last segment.
        if len(parts) >= 5:
            payer_name = parts[4]
    elif "PESALINK" in upper:
        channel = PaymentSource.BANK
        # PESALINK narration: sender name at position 2.
        if len(parts) >= 3:
            payer_name = parts[2]
    else:
        channel = PaymentSource.BANK
    return {
        "channel": channel,
        "payer_phone": payer_phone,
        "payer_name": payer_name,
        "tokens": [p for p in parts if p],
    }


def _resolve_tenant(payload: dict, parsed: dict):
    """Best-effort tenant match. Returns (tenant_or_None, matched_by, confident).

    Tiers, tried in order:
      1. Bill-ref tokens (high confidence — exact unit label or alias)
      2. Payer phone (low confidence — may be a relative)
      3. Payer name (low confidence — names can collide, typos happen)
    """
    candidates = list(parsed["tokens"])
    for key in ("BillRefNumber", "bill_ref", "CustMemoLine1", "CustMemoLine2", "CustMemoLine3"):
        val = payload.get(key)
        if val:
            candidates.append(str(val))
    for token in candidates:
        tenant = match_tenant(token)
        if tenant:
            return tenant, f"bill_ref:{token}", True
    if parsed["payer_phone"]:
        tenant = tenant_by_phone(parsed["payer_phone"])
        if tenant:
            return tenant, "phone", False
    if parsed.get("payer_name"):
        tenant = tenant_by_name(parsed["payer_name"])
        if tenant:
            return tenant, f"name:{parsed['payer_name']}", False
    return None, "", False


def _reversal_check(event_type: str, narration: str, payload: dict):
    """Decide whether a non-credit event is a reversal of a prior collection.

    Returns (is_reversal, original_event_or_None). A reversal is detected by a
    "REVERS" marker in the narration/memo, or by the debit referencing a prior
    RECORDED credit (its PaymentRef or TransactionId appearing in the text).
    NB: heuristic until a real reversal sample is seen — tune with Co-op's data.
    """
    if event_type == "CREDIT":
        return False, None
    text = " ".join(str(payload.get(k, "")) for k in (
        "Narration", "PaymentRef", "CustMemoLine1", "CustMemoLine2", "CustMemoLine3"))
    original = None
    for ev in CoopIpnEvent.objects.filter(
        status=CoopIpnStatus.RECORDED
    ).only("transaction_id", "payment_ref")[:500]:
        if (ev.payment_ref and ev.payment_ref in text) or (ev.transaction_id and ev.transaction_id in text):
            original = ev
            break
    is_reversal = "REVERS" in text.upper() or original is not None
    return is_reversal, original


def _safe_enqueue(task, *args) -> None:
    """Dispatch a Celery task without ever failing the bank ack (a broker outage
    must not turn into a non-200 / retry storm; review H5)."""
    try:
        task.delay(*args)
    except Exception:  # noqa: BLE001 — broker errors must not propagate
        logger.exception("Co-op IPN: failed to enqueue %s%r", getattr(task, "name", task), args)


class CoopIpnView(APIView):
    """POST /api/payments/coop/ipn/ — record Co-op credit notifications."""
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [CoopIpnThrottle]

    def post(self, request: Request, *_args, **_kwargs) -> Response:
        # Source-IP allowlist first: a request from outside Co-op's range is
        # forbidden regardless of whether it carries a (guessed) token (403).
        if not _ip_allowed(request):
            logger.warning("Co-op IPN: source IP %s not allowlisted — rejected", _client_ip(request))
            return Response({"MessageCode": "403", "Message": "Forbidden"}, status=403)
        if not _bearer_token_ok(request):
            logger.warning("Co-op IPN: invalid/missing bearer token — rejected")
            return Response({"MessageCode": "401", "Message": "Unauthorized"}, status=401)

        payload = request.data if isinstance(request.data, dict) else {}
        trans_id = str(payload.get("TransactionId", "")).strip()
        if not trans_id:
            logger.warning("Co-op IPN: payload missing TransactionId")
            return Response(_ipn_error("Missing TransactionId"), status=400)

        event_type = str(payload.get("EventType", "")).strip().upper()
        narration = payload.get("Narration", "") or ""
        parsed = _parse_narration(narration)
        acct = str(payload.get("AcctNo", "")).strip()
        expected_acct = str(getattr(settings, "COOP_ACCOUNT_NUMBER", "") or "").strip()

        try:
            amount = Decimal(str(payload.get("Amount", "0"))).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        except (InvalidOperation, TypeError):
            amount = Decimal("0")

        currency = str(payload.get("Currency", "") or "").strip().upper()

        receipt_args = None  # (tenant_id, amount_str, reference, posting_date_iso)

        try:
            with db_transaction.atomic():
                # Atomic claim — a duplicate TransactionId raises IntegrityError.
                event = CoopIpnEvent.objects.create(
                    transaction_id=trans_id,
                    payment_ref=str(payload.get("PaymentRef", "")).strip(),
                    account_number=acct,
                    amount=amount,
                    event_type=event_type,
                    channel=parsed["channel"],
                    narration=narration,
                    raw_payload=payload,
                    status=CoopIpnStatus.ERROR,  # provisional
                )

                if expected_acct and acct != expected_acct:
                    event.status = CoopIpnStatus.IGNORED
                    event.detail = "Credit to non-target account"
                elif currency and currency != "KES":
                    event.status = CoopIpnStatus.IGNORED
                    event.detail = f"Non-KES currency ({currency})"
                elif event_type != "CREDIT":
                    is_reversal, original = _reversal_check(event_type, narration, payload)
                    if is_reversal:
                        # Never auto-reverse a tenant's payment — hold for the
                        # authorising director (Dr. Osoro) to approve.
                        event.status = CoopIpnStatus.REVERSAL_PENDING
                        ref = original.transaction_id if original else "unknown original"
                        event.detail = f"Reversal (orig: {ref}) — awaiting director authorization"
                    else:
                        event.status = CoopIpnStatus.IGNORED
                        event.detail = f"Non-credit event ({event_type or 'missing'})"
                elif amount <= 0:
                    event.status = CoopIpnStatus.ERROR
                    event.detail = "Non-positive amount"
                else:
                    tenant, matched_by, confident = _resolve_tenant(payload, parsed)
                    if not tenant:
                        event.status = CoopIpnStatus.UNMATCHED
                        event.detail = "No tenant match"
                    elif not confident:
                        # Phone-only match: record the link for review but DON'T
                        # auto-create a Payment or notify the tenant (review H2).
                        event.status = CoopIpnStatus.UNMATCHED
                        event.detail = f"Low-confidence match ({matched_by}) — verify"
                    else:
                        d = _posting_date(payload)
                        # Arrears-first: clear oldest unpaid periods before current.
                        payments = allocate_payment_fifo(
                            tenant=tenant,
                            amount=amount,
                            payment_date=d,
                            source=parsed["channel"],
                            reference=trans_id,
                            notes=f"Co-op IPN ({parsed['channel']}); matched by {matched_by}; "
                                  f"ref {event.payment_ref}",
                        )
                        event.status = CoopIpnStatus.RECORDED
                        split = f" across {len(payments)} periods" if len(payments) > 1 else ""
                        event.detail = f"Matched by {matched_by}{split}"
                        event.payment = payments[0]  # representative link
                        # One receipt for the full deposit (not per chunk).
                        receipt_args = (tenant.id, str(amount), trans_id, d.isoformat())
                event.save()
        except IntegrityError:
            logger.info("Co-op IPN: duplicate TransactionId %s — acknowledged", trans_id)
            return Response(IPN_OK)

        # --- post-commit side effects & monitoring ---
        if event.status == CoopIpnStatus.RECORDED:
            _safe_enqueue(send_deposit_receipt, *receipt_args)
            logger.info("Co-op IPN: recorded %s KES %s (%s)", trans_id, amount, event.detail)
        elif event.status == CoopIpnStatus.REVERSAL_PENDING:
            # Bank reversal — alert the director to authorize; do NOT auto-apply.
            _safe_enqueue(send_reversal_authorization_alert, event.id)
            logger.warning("Co-op IPN: REVERSAL_PENDING %s KES %s — director alerted", trans_id, amount)
        elif event.status in (CoopIpnStatus.UNMATCHED, CoopIpnStatus.ERROR):
            # Alert the admin to reconcile (review item M1).
            _safe_enqueue(send_unmatched_credit_alert, event.id)
            logger.warning(
                "Co-op IPN: %s %s KES %s phone=%s — admin alerted",
                event.status, trans_id, amount, _mask_phone(parsed["payer_phone"]),
            )
        else:  # IGNORED
            logger.info("Co-op IPN: ignored %s — %s", trans_id, event.detail)

        return Response(IPN_OK)
