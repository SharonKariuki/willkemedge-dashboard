"""
Send a single test SMS through Africa's Talking and report the real outcome.

Usage (Render Shell or locally):
    python manage.py send_test_sms 0792682121
    python manage.py send_test_sms 0792682121 --message "Custom text"
    python manage.py send_test_sms 0792682121 --check-only

AT answers the send call with HTTP 200 even when the carrier rejects the
recipient, so a raw 200 tells you nothing. This command prints the active
credentials (masked), the normalised number, the full receipt, and the
per-recipient verdict from ``at_delivery_error`` — which is what actually
tells you whether the sender ID is live.
"""
from django.conf import settings
from django.core.management.base import BaseCommand

from apps.payments.notifications import at_delivery_error, send_sms, to_intl_phone

DEFAULT_MESSAGE = (
    "Test from Wilkem Edge: your rent statement notifications are now active. "
    "No action needed."
)


class Command(BaseCommand):
    help = "Send one test SMS via Africa's Talking and print the delivery verdict."

    def add_arguments(self, parser):
        parser.add_argument("phone", help="Recipient number (07…, 2547…, or +2547…).")
        parser.add_argument(
            "--message",
            default=DEFAULT_MESSAGE,
            help="Message body to send. Defaults to a short transactional test.",
        )
        parser.add_argument(
            "--check-only",
            action="store_true",
            help="Print the resolved config and normalised number without sending.",
        )

    def handle(self, *args, **opts):
        api_key = getattr(settings, "AT_API_KEY", "")
        username = getattr(settings, "AT_USERNAME", "sandbox")
        sender_id = getattr(settings, "AT_SENDER_ID", "")
        to = to_intl_phone(opts["phone"])

        self.stdout.write("Africa's Talking configuration")
        self.stdout.write(f"  AT_USERNAME  : {username or '(unset)'}")
        self.stdout.write(f"  AT_SENDER_ID : {sender_id or '(unset — AT will use a shared masked number)'}")
        self.stdout.write(f"  AT_API_KEY   : {'set (' + api_key[:6] + '…)' if api_key else '(unset)'}")
        self.stdout.write(f"  Environment  : {'sandbox' if username == 'sandbox' else 'live'}")
        self.stdout.write(f"  Recipient    : {opts['phone']} -> {to or '(could not normalise)'}")

        if not api_key:
            self.stderr.write(self.style.ERROR("AT_API_KEY is not set — nothing will be sent."))
            return
        if username == "sandbox":
            self.stdout.write(self.style.WARNING(
                "AT_USERNAME is 'sandbox' — this hits the sandbox API and will not reach a real handset."
            ))
        if not sender_id:
            self.stdout.write(self.style.WARNING(
                "AT_SENDER_ID is empty — Safaricom numbers will reject the message until the "
                "approved sender ID is configured."
            ))
        if not to:
            self.stderr.write(self.style.ERROR("Recipient number could not be normalised."))
            return
        if opts["check_only"]:
            self.stdout.write("\n--check-only set; no message sent.")
            return

        self.stdout.write("\nSending…")
        receipt = send_sms(to, opts["message"])
        self.stdout.write(f"Receipt: {receipt}")

        error = at_delivery_error(receipt)
        if error:
            self.stderr.write(self.style.ERROR(f"NOT DELIVERED: {error}"))
        else:
            self.stdout.write(self.style.SUCCESS("ACCEPTED for delivery by Africa's Talking."))
