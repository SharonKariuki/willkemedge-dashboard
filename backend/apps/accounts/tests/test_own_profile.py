"""Settings → Edit profile: a person changes their own name, not their login."""
import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import AuditLog, Role

User = get_user_model()


@pytest.fixture
def me(db):
    return User.objects.create_user(
        username="k@example.com", email="k@example.com", password="Rent-roll-2026!", role=Role.ACCOUNTANT,
    )


def _client(user):
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return c


def test_saves_my_name_and_logs_it(me):
    resp = _client(me).patch("/api/auth/me/", {"first_name": " Sharon ", "last_name": "Kariuki"}, format="json")
    assert resp.status_code == 200, resp.data
    assert resp.data["first_name"] == "Sharon" and resp.data["last_name"] == "Kariuki"
    me.refresh_from_db()
    assert me.get_full_name() == "Sharon Kariuki"
    assert AuditLog.objects.get(action="user.profile_update").summary == "Changed their name to Sharon Kariuki"


def test_cannot_change_my_login_email_or_role_here(me):
    resp = _client(me).patch("/api/auth/me/", {"email": "other@example.com", "role": Role.OWNER}, format="json")
    assert resp.status_code == 200
    me.refresh_from_db()
    assert me.email == "k@example.com" and me.role == Role.ACCOUNTANT


def test_saving_the_same_name_logs_nothing(me):
    _client(me).patch("/api/auth/me/", {"first_name": ""}, format="json")
    assert not AuditLog.objects.filter(action="user.profile_update").exists()


def test_signed_out_cannot_save(db):
    assert APIClient().patch("/api/auth/me/", {"first_name": "X"}, format="json").status_code == 401
