"""
Notification helpers — SMS via Africa's Talking, email via SendGrid.

All functions are thin wrappers. They raise on failure so the calling
Celery task can retry with exponential backoff.

Required settings (all optional in dev — if absent, notifications are
logged only):
    AT_API_KEY, AT_USERNAME, AT_SENDER_ID
    SENDGRID_API_KEY, DEFAULT_FROM_EMAIL
"""
import logging

from django.conf import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SMS — Africa's Talking
# ---------------------------------------------------------------------------

def send_sms(phone: str, message: str) -> None:
    """
    Send an SMS via Africa's Talking.
    Phone should be in international format: +2547XXXXXXXX
    """
    api_key = getattr(settings, "AT_API_KEY", "")
    username = getattr(settings, "AT_USERNAME", "sandbox")

    if not api_key:
        logger.warning("SMS skipped (AT_API_KEY not set): to=%s msg=%s", phone, message)
        return

    try:
        import africastalking
        africastalking.initialize(username, api_key)
        sms = africastalking.SMS
        sender = getattr(settings, "AT_SENDER_ID", None)
        response = sms.send(message, [phone], sender_id=sender)
        logger.info("SMS sent to %s: %s", phone, response)
    except Exception as exc:
        logger.error("SMS failed to %s: %s", phone, exc)
        raise


# ---------------------------------------------------------------------------
# Email — SendGrid
# ---------------------------------------------------------------------------

def send_email(
    to_email: str,
    subject: str,
    html_content: str,
    text_content: str = "",
) -> None:
    """Send a transactional email via SendGrid."""
    api_key = getattr(settings, "SENDGRID_API_KEY", "")
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@willkemedge.co.ke")

    if not api_key:
        logger.warning("Email skipped (SENDGRID_API_KEY not set): to=%s subj=%s", to_email, subject)
        return

    try:
        import sendgrid
        from sendgrid.helpers.mail import Content, Email, Mail, To

        sg = sendgrid.SendGridAPIClient(api_key=api_key)
        mail = Mail(
            from_email=Email(from_email),
            to_emails=To(to_email),
            subject=subject,
        )
        mail.add_content(Content("text/plain", text_content or ""))
        mail.add_content(Content("text/html", html_content))

        response = sg.client.mail.send.post(request_body=mail.get())
        logger.info("Email sent to %s (status %s)", to_email, response.status_code)
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
