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
    """Send password reset link to the user's email via Gmail SMTP."""
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


class EmailNotSent(Exception):
    """The mail backend skipped the message (no credentials, or a suppressed recipient)."""


def deliver_invite_email(invite) -> None:
    """Send the invite now. Raises if it doesn't go, so the caller can say why.

    Called straight from the request rather than through Celery: production
    has no worker (tasks run eagerly), and an eager task's retry surfaced as a
    server error after the invite was already saved - with no email sent and
    no reason shown.
    """
    from html import escape

    from django.conf import settings

    from apps.payments.notifications import send_email

    from .models import AccountInvite

    user = invite.user
    frontend_url = getattr(settings, "FRONTEND_URL", "http://localhost:5173")
    link = f"{frontend_url}/invite/{invite.token}"
    inviter = invite.created_by
    who = escape(inviter.get_full_name() or inviter.email) if inviter else "Wilkem Ventures"
    name = escape(user.first_name or "there")

    html = f"""
<html><body style="font-family:Inter,Segoe UI,sans-serif;color:#0F172A;padding:24px;max-width:520px">
  <p style="color:#0D9488;font-size:12px;font-weight:600;letter-spacing:.08em;margin:0 0 8px">
    WILKEM VENTURES</p>
  <h2 style="color:#0F2A43;margin:0 0 16px">You've been invited to the rental dashboard</h2>
  <p>Hi {name},</p>
  <p>{who} has given you access to the Wilkem Ventures rental dashboard as
     <strong>{escape(user.get_role_display())}</strong>.</p>
  <p>Choose your password to finish setting up your account. You'll sign in with
     <strong>{escape(user.email)}</strong>.</p>
  <p style="margin:24px 0"><a href="{link}" style="background:#0F2A43;color:#ffffff;padding:11px 22px;
     border-radius:999px;text-decoration:none;font-weight:600">Set my password</a></p>
  <p style="color:#64748B;font-size:12px">This link works once and expires in
     {AccountInvite.EXPIRY_HOURS // 24} days. If you weren't expecting it, ignore this email
     and no account will be opened.</p>
</body></html>"""

    if not send_email(user.email, "Your invitation to the Wilkem Ventures dashboard", html):
        raise EmailNotSent(
            "The server skipped it: either email isn't set up on the server, or this address belongs "
            "to a tenant and tenant email is switched off."
        )
    logger.info("Invite email sent to %s", user.email)


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def send_invite_email(self, invite_id: int) -> None:
    """For a Celery worker, if one is ever run. The dashboard calls deliver_invite_email directly."""
    from .models import AccountInvite

    invite = AccountInvite.objects.select_related("user", "created_by").filter(pk=invite_id).first()
    if invite is None or not invite.is_valid:
        logger.info("send_invite_email: invite %s is gone or no longer valid", invite_id)
        return
    try:
        deliver_invite_email(invite)
    except Exception as exc:
        raise self.retry(exc=exc, countdown=30 * (2 ** self.request.retries)) from exc
