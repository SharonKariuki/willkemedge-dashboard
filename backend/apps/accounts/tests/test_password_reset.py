"""
Tests for password reset flow.

Covers:
  - POST /api/auth/password-reset/ returns 200 for any email (no enumeration)
  - Valid token → password changed, token marked used
  - Expired token → 400
  - Already-used token → 400
  - send_password_reset_email task dispatched
"""
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import PasswordResetToken

User = get_user_model()

REQUEST_URL = "/api/auth/password-reset/"
CONFIRM_URL = "/api/auth/password-reset/confirm/"


@pytest.fixture
def admin_user(db):
    return User.objects.create_user(
        username="admin", email="william@gmail.com",
        password="SecurePass123!",
    )


@pytest.fixture
def client():
    return APIClient()


@pytest.mark.django_db
class TestPasswordResetRequest:
    @patch("apps.accounts.tasks.send_password_reset_email.delay")
    def test_returns_200_for_existing_email(self, mock_task, client, admin_user):
        resp = client.post(REQUEST_URL, {"email": "william@gmail.com"}, format="json")
        assert resp.status_code == 200
        mock_task.assert_called_once()

    def test_returns_200_for_nonexistent_email(self, client, db):
        """Must NOT leak whether email exists."""
        resp = client.post(REQUEST_URL, {"email": "ghost@example.com"}, format="json")
        assert resp.status_code == 200

    def test_returns_200_for_invalid_email_format(self, client, db):
        """Anti-enumeration: always 200 even for junk input."""
        resp = client.post(REQUEST_URL, {"email": "not-an-email"}, format="json")
        assert resp.status_code == 200


@pytest.mark.django_db
class TestPasswordResetConfirm:
    def test_valid_token_changes_password(self, client, admin_user):
        token_obj = PasswordResetToken.create_for_user(admin_user)
        resp = client.post(CONFIRM_URL, {
            "token": token_obj.token,
            "new_password": "NewSecurePass456!",
        }, format="json")
        assert resp.status_code == 200
        admin_user.refresh_from_db()
        assert admin_user.check_password("NewSecurePass456!")

    def test_valid_token_is_marked_used(self, client, admin_user):
        token_obj = PasswordResetToken.create_for_user(admin_user)
        client.post(CONFIRM_URL, {
            "token": token_obj.token,
            "new_password": "NewSecurePass456!",
        }, format="json")
        token_obj.refresh_from_db()
        assert token_obj.used is True

    def test_used_token_rejected(self, client, admin_user):
        token_obj = PasswordResetToken.create_for_user(admin_user)
        token_obj.used = True
        token_obj.save()
        resp = client.post(CONFIRM_URL, {
            "token": token_obj.token,
            "new_password": "NewSecurePass456!",
        }, format="json")
        assert resp.status_code == 400

    def test_expired_token_rejected(self, client, admin_user):
        token_obj = PasswordResetToken.create_for_user(admin_user)
        PasswordResetToken.objects.filter(pk=token_obj.pk).update(
            created_at=timezone.now() - timedelta(minutes=20)
        )
        resp = client.post(CONFIRM_URL, {
            "token": token_obj.token,
            "new_password": "NewSecurePass456!",
        }, format="json")
        assert resp.status_code == 400

    def test_nonexistent_token_rejected(self, client, db):
        resp = client.post(CONFIRM_URL, {
            "token": "completely-made-up-token-xyz",
            "new_password": "NewSecurePass456!",
        }, format="json")
        assert resp.status_code == 400

    def test_weak_password_rejected(self, client, admin_user):
        token_obj = PasswordResetToken.create_for_user(admin_user)
        resp = client.post(CONFIRM_URL, {
            "token": token_obj.token,
            "new_password": "123",
        }, format="json")
        assert resp.status_code == 400
