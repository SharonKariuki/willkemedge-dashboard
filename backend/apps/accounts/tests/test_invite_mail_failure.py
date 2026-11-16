"""When the invite email can't be sent, the invite still stands and the page says why.

Production runs Celery tasks eagerly with no worker. The invite email used to
go through a task whose retry, run eagerly, surfaced as a 500 after the
invite was saved - so the person was listed as invited, no email arrived, and
nothing said why. These run the real send path with only SMTP faked.
"""
import smtplib
from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import AccountInvite, Role

User = get_user_model()
USERS = "/api/auth/users/"
SMTP_SEND = "django.core.mail.message.EmailMessage.send"


@pytest.fixture
def owner(db):
    return User.objects.create_user(username="o@example.com", email="o@example.com", password="x" * 14, role=Role.OWNER)


@pytest.fixture(autouse=True)
def mail_configured(settings):
    settings.EMAIL_HOST_USER = "sender@example.com"
    settings.EMAIL_HOST_PASSWORD = "app-password"


def _client(user):
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return c


def _invite(owner):
    return _client(owner).post(USERS, {"email": "j@example.com", "role": Role.VIEWER}, format="json")


def test_the_invite_email_is_sent(owner, mailoutbox):
    resp = _invite(owner)
    assert resp.status_code == 201
    assert resp.data["email_error"] is None
    assert len(mailoutbox) == 1 and mailoutbox[0].to == ["j@example.com"]
    assert AccountInvite.objects.get(user__email="j@example.com").token in mailoutbox[0].alternatives[0][0]


def test_a_refused_sign_in_keeps_the_invite_and_says_why(owner):
    err = smtplib.SMTPAuthenticationError(535, b"Username and Password not accepted")
    with mock.patch(SMTP_SEND, side_effect=err):
        resp = _invite(owner)
    assert resp.status_code == 201
    assert resp.data["status"] == "invited"
    assert "refused the sign-in" in resp.data["email_error"]
    assert "SMTPAuthenticationError" in resp.data["email_error"]


def test_an_unreachable_mail_server_is_named(owner):
    with mock.patch(SMTP_SEND, side_effect=TimeoutError("timed out")):
        resp = _invite(owner)
    assert resp.status_code == 201
    assert "couldn't reach the mail server" in resp.data["email_error"]


def test_no_mail_settings_is_named(owner, settings):
    settings.EMAIL_HOST_PASSWORD = ""
    resp = _invite(owner)
    assert resp.status_code == 201
    assert "isn't set up" in resp.data["email_error"]


def test_resend_reports_the_email_outcome(owner, mailoutbox):
    with mock.patch(SMTP_SEND, side_effect=TimeoutError("timed out")):
        _invite(owner)
    jane = User.objects.get(email="j@example.com")
    resp = _client(owner).post(f"{USERS}{jane.pk}/resend/")
    assert resp.status_code == 200
    assert resp.data["email_error"] is None and len(mailoutbox) == 1


def test_a_failed_reset_email_does_not_error_or_give_anything_away(owner):
    with mock.patch(SMTP_SEND, side_effect=TimeoutError("timed out")):
        known = APIClient().post("/api/auth/password-reset/", {"email": "o@example.com"}, format="json")
    unknown = APIClient().post("/api/auth/password-reset/", {"email": "nobody@example.com"}, format="json")
    assert known.status_code == unknown.status_code == 200
    assert known.data == unknown.data
