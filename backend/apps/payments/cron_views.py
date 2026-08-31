"""
HTTP triggers for the scheduled jobs.

There is no Celery beat process in production. Running one would mean paying for
a Render worker plus a Redis instance, which is hard to justify at this scale, so
a **free** external scheduler (cron-job.org, GitHub Actions, UptimeRobot) calls
these endpoints instead. This generalises the pattern already used by
`reconciliation_views.py`.

    GET|POST /api/payments/cron/<job>/
      Headers:  Authorization: Bearer <CRON_TRIGGER_TOKEN>
      Query:    token=<CRON_TRIGGER_TOKEN>    (alternative; many free cron
                services cannot send custom headers)
      Optional: ?date=YYYY-MM-DD              (daily-reconciliation only)

Jobs run **synchronously** via `.apply()`, so they work with no broker and no
worker, and a failure surfaces as a 500 — which makes the scheduler's run show
red instead of failing silently.

Schedule (times are EAT; see .github/workflows/scheduled-jobs.yml):

    06:30, 25th of month  monthly-arrears        (raises NEXT month)
    07:00, 25th of month  monthly-statements     (emails NEXT month)
    00:05, 1st of month   monthly-arrears        (catch-up)
    00:30 daily           recalculate-statuses
    08:00 daily           rent-reminders
    09:00 daily           arrears-reminders
    any time daily        daily-reconciliation

The two monthly jobs run a month ahead of the calendar, at tenants' request: on
25 August they raise and email September, so the bill arrives before the month
it covers rather than after it has started. `apps/payments/billing_calendar.py`
owns that rule and lists what else depends on it.

Order matters on the 25th. `monthly-arrears` is what raises the month's rent,
and a statement emailed before it has run states a balance with the stated month
missing from it — hence the half hour between them.

`monthly-statements` accepts an optional `?period=YYYY-MM` to re-issue a month;
without it the job bills whichever month the cycle is on.

`monthly-arrears` is the important one: it is the only thing that creates an
Arrears row for a tenant who has *not* paid. Without it, defaulters produce no
arrears record at all and stay invisible to the reminders and the arrears report.
It bills every month a tenant is short of, so the 1st-of-month run is a free
safety net for a 25th that failed.
"""
import hmac
import logging

from django.conf import settings
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .tasks import (
    generate_monthly_arrears,
    recalculate_all_statuses,
    send_arrears_reminders,
    send_daily_reconciliation,
    send_monthly_statements,
    send_rent_reminders,
)

logger = logging.getLogger(__name__)

# Slug → task. Kept explicit rather than resolved dynamically from the request so
# the endpoint can never be coaxed into running an arbitrary task.
JOBS = {
    "rent-reminders": send_rent_reminders,
    "arrears-reminders": send_arrears_reminders,
    "recalculate-statuses": recalculate_all_statuses,
    "monthly-arrears": generate_monthly_arrears,
    "daily-reconciliation": send_daily_reconciliation,
    "monthly-statements": send_monthly_statements,
}


def expected_token() -> str:
    """The configured trigger secret, or "" when none is set."""
    return getattr(settings, "CRON_TRIGGER_TOKEN", "") or getattr(
        settings, "RECONCILIATION_TRIGGER_TOKEN", ""
    )


def token_ok(request: Request) -> bool:
    """Constant-time check of the bearer token or ?token= query parameter."""
    expected = expected_token()
    if not expected:
        logger.error("Cron trigger rejected: CRON_TRIGGER_TOKEN not set")
        return False

    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        provided = header[len("Bearer "):].strip()
    else:
        provided = str(request.query_params.get("token", ""))

    return bool(provided) and hmac.compare_digest(provided, expected)


class ScheduledJobTriggerView(APIView):
    """Token-gated endpoint that runs one scheduled job synchronously."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request: Request, job: str, *_a, **_kw) -> Response:
        return self._run(request, job)

    def post(self, request: Request, job: str, *_a, **_kw) -> Response:
        return self._run(request, job)

    def _run(self, request: Request, job: str) -> Response:
        if not token_ok(request):
            return Response({"detail": "Unauthorized"}, status=401)

        task = JOBS.get(job)
        if task is None:
            return Response(
                {"detail": f"Unknown job '{job}'.", "jobs": sorted(JOBS)},
                status=404,
            )

        # Two jobs take an optional date argument; the rest take none.
        args = ()
        if job == "daily-reconciliation":
            args = (request.query_params.get("date") or None,)
        elif job == "monthly-statements":
            args = (request.query_params.get("period") or None,)

        logger.info("Cron trigger running job=%s", job)
        result = task.apply(args=args).get()

        return Response({"status": "ok", "job": job, "result": result}, status=200)
