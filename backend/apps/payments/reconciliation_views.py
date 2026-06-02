"""
HTTP trigger for the daily IPN reconciliation summary.

Lets a free external scheduler (cron-job.org, GitHub Actions, UptimeRobot,
etc.) fire the daily summary at no extra cost — so we don't need to pay for
Render's Cron Job add-on.

GET (or POST) /api/payments/coop/reconcile-daily/
  Headers:  Authorization: Bearer <RECONCILIATION_TRIGGER_TOKEN>
  Query:    token=<RECONCILIATION_TRIGGER_TOKEN>   (alternative; many free
            cron services don't support custom headers)
  Optional: ?date=YYYY-MM-DD   to backfill a specific day

Returns:
  200 {"status":"ok", "date": <yyyy-mm-dd>}     on success
  401 {"detail":"Unauthorized"}                  on bad/missing token
"""
import hmac
import logging

from django.conf import settings
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .tasks import send_daily_reconciliation

logger = logging.getLogger(__name__)


class DailyReconciliationTriggerView(APIView):
    """Token-gated endpoint that runs the daily summary synchronously."""
    permission_classes = [AllowAny]
    authentication_classes = []

    def _token_ok(self, request: Request) -> bool:
        expected = getattr(settings, "RECONCILIATION_TRIGGER_TOKEN", "")
        if not expected:
            logger.error("Reconciliation trigger rejected: RECONCILIATION_TRIGGER_TOKEN not set")
            return False
        header = request.headers.get("Authorization", "")
        if header.startswith("Bearer "):
            provided = header[len("Bearer "):].strip()
        else:
            provided = str(request.query_params.get("token", ""))
        return bool(provided) and hmac.compare_digest(provided, expected)

    def get(self, request: Request, *_a, **_kw) -> Response:
        return self._run(request)

    def post(self, request: Request, *_a, **_kw) -> Response:
        return self._run(request)

    def _run(self, request: Request) -> Response:
        if not self._token_ok(request):
            return Response({"detail": "Unauthorized"}, status=401)

        date_iso = request.query_params.get("date") or None
        # apply() runs synchronously and surfaces errors as a 500 to the caller
        # so the scheduler's run shows red if anything broke.
        send_daily_reconciliation.apply(args=(date_iso,)).get()
        return Response({"status": "ok", "date": date_iso or "yesterday"}, status=200)
