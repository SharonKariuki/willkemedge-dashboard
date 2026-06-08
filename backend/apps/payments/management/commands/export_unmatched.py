"""
Export unmatched (or any-status) Co-op IPN events as tab-separated values
suitable for pasting straight into Google Sheets or Excel.

Usage (Render Shell):
    python manage.py export_unmatched
    python manage.py export_unmatched --status all
    python manage.py export_unmatched --status reversal_pending

The output has trailing blank columns ("Which unit?" / "Which tenant?")
so the property owner can fill them in directly on the shared sheet.
"""
from django.core.management.base import BaseCommand

from apps.payments.models import CoopIpnEvent, CoopIpnStatus


def _strip_mpesa_prefix(bill_ref: str) -> str:
    """Show just what the tenant typed after '90290#' — empty if they only typed the prefix."""
    if not bill_ref:
        return ""
    s = bill_ref.strip()
    for prefix in ("90290#", "90290"):
        if s.upper().startswith(prefix.upper()):
            s = s[len(prefix):]
            break
    return s.lstrip("#").strip()


class Command(BaseCommand):
    help = "Export Co-op IPN events as tab-separated values (paste into Google Sheets)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--status",
            default="unmatched",
            help="Status to export (unmatched, recorded, reversal_pending, all). Default: unmatched.",
        )

    def handle(self, *args, **opts):
        status = opts["status"].lower()
        qs = CoopIpnEvent.objects.all().order_by("received_at")
        if status != "all":
            valid = {c.value for c in CoopIpnStatus}
            if status not in valid:
                self.stderr.write(f"Invalid --status. Choose from: {sorted(valid) + ['all']}")
                return
            qs = qs.filter(status=status)

        cols = [
            "Date", "Time", "Channel", "Amount (KES)",
            "Bill Ref Typed", "Payer Phone", "Payer Name",
            "Bank Reference / Notes", "Transaction ID",
            "Which unit?", "Which tenant?", "Notes",
        ]
        print("\t".join(cols))

        for e in qs:
            parts = (e.narration or "").split("~")
            if e.channel == "mpesa":
                # code ~ billref ~ phone ~ MPESAC2B_paybill ~ payer name
                bill_ref = _strip_mpesa_prefix(parts[1] if len(parts) > 1 else "")
                phone = parts[2] if len(parts) > 2 else ""
                name = parts[4] if len(parts) > 4 else ""
                notes = ""
            else:
                # PESALINK ~ ref ~ sender name ~ sender account ~ ?? ~ reference text
                bill_ref = ""
                phone = ""
                name = parts[2] if len(parts) > 2 else ""
                notes = parts[5] if len(parts) > 5 else ""

            row = [
                e.received_at.strftime("%Y-%m-%d"),
                e.received_at.strftime("%H:%M"),
                e.get_channel_display(),
                f"{e.amount:.2f}",
                bill_ref,
                phone,
                name,
                notes,
                e.transaction_id,
                "",  # Which unit? — for the owner to fill in
                "",  # Which tenant? — for the owner to fill in
                "",  # Notes — for the owner to fill in
            ]
            print("\t".join(str(c) for c in row))
