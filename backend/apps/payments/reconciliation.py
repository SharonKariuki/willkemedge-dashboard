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


# Plain-English labels so a non-technical reader (Dr. Osoro) understands what
# happened to each payment without knowing internal status names. Keep these
# friendly and concrete; avoid "IPN", "event", "credit", etc.
_FRIENDLY = {
    CoopIpnStatus.RECORDED: "Matched to a tenant and recorded",
    CoopIpnStatus.UNMATCHED: "Could not be auto-matched (needs review)",
    CoopIpnStatus.DUPLICATE: "Duplicate of an earlier payment (already handled)",
    CoopIpnStatus.IGNORED: "Ignored (bank fees / non-rent)",
    CoopIpnStatus.REVERSAL_PENDING: "Bank reversal — needs your authorization",
    CoopIpnStatus.REVERSAL_APPLIED: "Bank reversal applied (with your authorization)",
    CoopIpnStatus.ERROR: "Could not be processed (needs technical review)",
}


def _friendly(status: str) -> str:
    return _FRIENDLY.get(status, status.replace("_", " ").capitalize())


def _pl(n: int, word: str) -> str:
    """'1 payment' / '5 payments'."""
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def render_summary_text(summary: dict[str, Any]) -> str:
    """Plain-language email body. Paragraphs are separated by `\\n\\n` so the
    HTML wrapper renders each as its own block."""
    date = summary["date"]
    total_count = summary["total_count"]
    total_amount = summary["total_amount"]
    needs = summary["needs_attention"]

    if total_count == 0:
        return (
            "Good morning,\n\n"
            f"No rent payments came in to Paybill 400222 on {date}.\n\n"
            "— Wilkem Edge"
        )

    paragraphs = [
        "Good morning,",
        f"Here is the summary of rent payments received for Paybill 400222 on {date}.",
        f"Total payments received: {total_count}",
        f"Total amount received: KES {total_amount:,.2f}",
        "Breakdown:",
    ]
    for status in sorted(summary["by_status"].keys()):
        row = summary["by_status"][status]
        paragraphs.append(
            f"• {_friendly(status)} — {_pl(row['count'], 'payment')}, "
            f"KES {row['total']:,.2f}"
        )

    if needs:
        verb = "needs" if needs == 1 else "need"
        paragraphs.append(
            f"⚠ {_pl(needs, 'item')} {verb} your attention. "
            "Please log in to the dashboard to review them — either assign "
            "the payment to the correct tenant, or authorize the bank reversal."
        )
    else:
        paragraphs.append("Everything is reconciled — no action needed.")

    paragraphs.append("— Wilkem Edge")
    return "\n\n".join(paragraphs)


def render_summary_sms(summary: dict[str, Any]) -> str:
    """Single-line SMS — short enough to fit in one segment."""
    date = summary["date"]
    if summary["total_count"] == 0:
        return f"Wilkem Edge {date}: no rent payments received."
    base = (
        f"Wilkem Edge {date}: "
        f"{_pl(summary['total_count'], 'payment')}, "
        f"KES {summary['total_amount']:,.0f}."
    )
    needs = summary["needs_attention"]
    if needs:
        verb = "needs" if needs == 1 else "need"
        return f"{base} {needs} {verb} your attention — log in to review."
    return f"{base} All clear, no action needed."
