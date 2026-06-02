"""
Daily IPN reconciliation.

A one-page summary of yesterday's Co-op IPN events: how many credits landed,
how many matched, how many need attention. Emailed (and optionally SMSed)
each morning to the admin + director so anything stuck is seen immediately,
not when a tenant complains.

Kept deliberately minimal — at this scale, a single email IS the dashboard.
"""
import datetime as dt
import logging
from decimal import Decimal
from typing import Any

from django.db.models import Count, Sum
from django.utils import timezone

from .models import CoopIpnEvent, CoopIpnStatus

logger = logging.getLogger(__name__)


def _target_date(d: dt.date | None = None) -> dt.date:
    """Default to *yesterday* in the project timezone, so a 06:00 cron job
    reports a complete prior day."""
    if d is not None:
        return d
    today = timezone.localdate()
    return today - dt.timedelta(days=1)


def build_daily_reconciliation_summary(target: dt.date | None = None) -> dict[str, Any]:
    """Aggregate the day's IPN events by status. Pure function — no I/O."""
    target = _target_date(target)
    start = timezone.make_aware(dt.datetime.combine(target, dt.time.min))
    end = start + dt.timedelta(days=1)
    qs = CoopIpnEvent.objects.filter(received_at__gte=start, received_at__lt=end)

    by_status_qs = qs.values("status").annotate(
        n=Count("id"), total=Sum("amount")
    )
    by_status = {
        row["status"]: {
            "count": row["n"],
            "total": Decimal(row["total"] or 0).quantize(Decimal("0.01")),
        }
        for row in by_status_qs
    }

    total_amount = sum(
        (row["total"] for row in by_status.values()), Decimal("0")
    ).quantize(Decimal("0.01"))
    total_count = sum(row["count"] for row in by_status.values())
    needs_attention = (
        by_status.get(CoopIpnStatus.UNMATCHED, {}).get("count", 0)
        + by_status.get(CoopIpnStatus.REVERSAL_PENDING, {}).get("count", 0)
        + by_status.get(CoopIpnStatus.ERROR, {}).get("count", 0)
    )

    return {
        "date": target.isoformat(),
        "total_count": total_count,
        "total_amount": total_amount,
        "needs_attention": needs_attention,
        "by_status": by_status,
    }


def _label(status: str) -> str:
    return dict(CoopIpnStatus.choices).get(status, status)


def render_summary_text(summary: dict[str, Any]) -> str:
    """Plain-text body suitable for email + SMS (short form)."""
    lines = [
        f"Wilkem Edge — Co-op IPN reconciliation for {summary['date']}",
        "",
        f"Events:  {summary['total_count']}",
        f"Total:   KES {summary['total_amount']:,.2f}",
        f"Needs attention: {summary['needs_attention']}",
        "",
        "Breakdown:",
    ]
    if not summary["by_status"]:
        lines.append("  (no IPN events received on this day)")
    else:
        for status, row in sorted(summary["by_status"].items()):
            lines.append(
                f"  {_label(status):<35} {row['count']:>4}   KES {row['total']:>12,.2f}"
            )
    if summary["needs_attention"]:
        lines.append("")
        lines.append("Open the dashboard (Admin → Co-op IPN events) and reconcile.")
    return "\n".join(lines)


def render_summary_sms(summary: dict[str, Any]) -> str:
    needs = summary["needs_attention"]
    suffix = f" — {needs} need attention" if needs else " — all clear"
    return (
        f"Wilkem IPN {summary['date']}: {summary['total_count']} events, "
        f"KES {summary['total_amount']:,.0f}{suffix}."
    )
