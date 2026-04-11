"""
Celery tasks for the accounts app.

Tasks:
  send_password_reset_email  — dispatched by PasswordResetRequestView
"""
import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def send_password_reset_email(self, user_id: int, token: str) -> None:
    """Send password reset link to the user's email via SendGrid."""
    from django.conf import settings
    from django.contrib.auth import get_user_model

    from apps.payments.notifications import send_email

    User = get_user_model()
    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        logger.error("send_password_reset_email: user %s not found", user_id)
        return

    frontend_url = getattr(settings, "FRONTEND_URL", "http://localhost:5173")
    reset_url = f"{frontend_url}/reset-password/confirm/{token}"

    html = f"""
<html><body style="font-family:sans-serif;color:#1e293b;padding:24px">
  <h2>Password Reset Request</h2>
  <p>Hi {user.username},</p>
  <p>Click the link below to reset your password. This link expires in 15 minutes.</p>
  <p><a href="{reset_url}" style="background:#2563eb;color:white;padding:10px 20px;
     border-radius:6px;text-decoration:none">Reset Password</a></p>
  <p style="color:#64748b;font-size:12px">If you didn't request this, ignore this email.</p>
</body></html>"""

    try:
        send_email(user.email, "Reset your password — Dr. Osoro Dashboard", html)
        logger.info("Password reset email sent to %s", user.email)
    except Exception as exc:
        raise self.retry(exc=exc, countdown=30 * (2 ** self.request.retries)) from exc
