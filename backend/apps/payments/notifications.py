"""
Notification helpers — SMS via Africa's Talking, email via SMTP.

All functions are thin wrappers. They raise on failure so the calling
Celery task can retry with exponential backoff.

Required settings (all optional in dev — if absent, notifications are
logged only):
    AT_API_KEY, AT_USERNAME, AT_SENDER_ID
    EMAIL_HOST_USER, EMAIL_HOST_PASSWORD, DEFAULT_FROM_EMAIL
"""
import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SMS — Africa's Talking
# ---------------------------------------------------------------------------

def send_sms(phone: str, message: str) -> None:
    """
    Send an SMS via Africa's Talking REST API (using httpx).

    We call the API directly instead of the `africastalking` SDK because
    the SDK's `requests` dependency hits an SSL error on Windows with
    urllib3 2.x.  httpx works reliably.

    Phone should be in international format: +2547XXXXXXXX
    """
    import httpx

    api_key = getattr(settings, "AT_API_KEY", "")
    username = getattr(settings, "AT_USERNAME", "sandbox")

    if not api_key:
        logger.warning("SMS skipped (AT_API_KEY not set): to=%s msg=%s", phone, message)
        return

    env = "sandbox" if username == "sandbox" else "live"
    base = f"https://api.{env}.africastalking.com" if env == "sandbox" else "https://api.africastalking.com"

    try:
        resp = httpx.post(
            f"{base}/version1/messaging",
            headers={
                "apiKey": api_key,
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"username": username, "to": phone, "message": message},
            timeout=15,
        )
        resp.raise_for_status()
        logger.info("SMS sent to %s: %s", phone, resp.json())
    except Exception as exc:
        logger.error("SMS failed to %s: %s", phone, exc)
        raise


# ---------------------------------------------------------------------------
# Email — SMTP (Gmail in dev/MVP, swap host for any other SMTP provider)
# ---------------------------------------------------------------------------

def send_email(
    to_email: str,
    subject: str,
    html_content: str,
    text_content: str = "",
) -> None:
    """Send a transactional email via SMTP (Django's built-in mail backend)."""
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@willkemedge.co.ke")
    user = getattr(settings, "EMAIL_HOST_USER", "")
    password = getattr(settings, "EMAIL_HOST_PASSWORD", "")

    if not user or not password:
        logger.warning(
            "Email skipped (EMAIL_HOST_USER/PASSWORD not set): to=%s subj=%s",
            to_email, subject,
        )
        return

    try:
        msg = EmailMultiAlternatives(
            subject=subject,
            body=text_content or "",
            from_email=from_email,
            to=[to_email],
        )
        msg.attach_alternative(html_content, "text/html")
        msg.send(fail_silently=False)
        logger.info("Email sent to %s", to_email)
    except Exception as exc:
        logger.error("Email failed to %s: %s", to_email, exc)
        raise


# ---------------------------------------------------------------------------
# Message builders
# ---------------------------------------------------------------------------

def payment_sms_message(tenant_name: str, amount, unit_label: str, reference: str) -> str:
    return (
        f"Dear {tenant_name}, payment of KES {amount:,.2f} received "
        f"for Unit {unit_label}. Ref: {reference}. Thank you - Dr. Osoro Properties."
    )


def payment_email_html(tenant_name: str, amount, unit_label: str,
                        period: str, reference: str) -> str:
    return f"""
<html><body style="font-family:sans-serif;color:#1e293b;padding:24px">
  <h2 style="color:#16a34a">Payment Received</h2>
  <p>Dear {tenant_name},</p>
  <p>We have received your payment:</p>
  <table style="border-collapse:collapse;width:100%;max-width:400px">
    <tr><td style="padding:8px;border:1px solid #e2e8f0"><b>Amount</b></td>
        <td style="padding:8px;border:1px solid #e2e8f0">KES {amount:,.2f}</td></tr>
    <tr><td style="padding:8px;border:1px solid #e2e8f0"><b>Unit</b></td>
        <td style="padding:8px;border:1px solid #e2e8f0">{unit_label}</td></tr>
    <tr><td style="padding:8px;border:1px solid #e2e8f0"><b>Period</b></td>
        <td style="padding:8px;border:1px solid #e2e8f0">{period}</td></tr>
    <tr><td style="padding:8px;border:1px solid #e2e8f0"><b>Reference</b></td>
        <td style="padding:8px;border:1px solid #e2e8f0">{reference}</td></tr>
  </table>
  <p style="margin-top:16px">Dr. Osoro Properties</p>
</body></html>"""


def custom_email_html(subject: str, body: str) -> str:
    """Wrap a plain-text body as a simple branded HTML email."""
    paragraphs = "".join(
        f"<p style=\"margin:0 0 12px\">{line}</p>"
        for line in body.strip().split("\n\n")
        if line.strip()
    )
    return f"""
<html><body style="font-family:sans-serif;color:#1e293b;padding:24px;max-width:560px">
  <h2 style="color:#16a34a;margin:0 0 16px">{subject}</h2>
  {paragraphs}
  <hr style="border:none;border-top:1px solid #e2e8f0;margin:24px 0" />
  <p style="font-size:12px;color:#64748b;margin:0">Dr. Osoro Properties</p>
</body></html>"""
