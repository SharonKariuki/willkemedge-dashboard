"""End-to-end tests for the auth flow: login, lockout, audit, refresh, logout."""
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import LoginAttempt
from apps.accounts.services import LOCKOUT_THRESHOLD

User = get_user_model()


class AuthFlowTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.password = "CorrectHorseBattery9!"
        cls.user = User.objects.create_user(
            username="owner",
            email="owner@example.com",
            password=cls.password,
        )

    def setUp(self):
        self.client = APIClient()
        self.login_url = reverse("accounts:login")

    def test_login_success_returns_tokens_and_user(self):
        response = self.client.post(
            self.login_url,
            {"email": "owner@example.com", "password": self.password},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert "access" in body and "refresh" in body
        assert body["user"]["email"] == "owner@example.com"

    def test_login_success_records_audit_row(self):
        self.client.post(
            self.login_url,
            {"email": "owner@example.com", "password": self.password},
            format="json",
        )
        attempt = LoginAttempt.objects.latest("attempted_at")
        assert attempt.email == "owner@example.com"
        assert attempt.successful is True

    def test_login_email_is_case_insensitive(self):
        response = self.client.post(
            self.login_url,
            {"email": "OWNER@example.com", "password": self.password},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK

    def test_login_wrong_password_returns_400_and_audits(self):
        response = self.client.post(
            self.login_url,
            {"email": "owner@example.com", "password": "wrong"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        attempt = LoginAttempt.objects.latest("attempted_at")
        assert attempt.successful is False

    def test_login_unknown_email_returns_400_and_audits(self):
        response = self.client.post(
            self.login_url,
            {"email": "ghost@example.com", "password": "whatever123"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert LoginAttempt.objects.filter(email="ghost@example.com").count() == 1

    def test_account_locks_after_threshold_failed_attempts(self):
        for _ in range(LOCKOUT_THRESHOLD):
            self.client.post(
                self.login_url,
                {"email": "owner@example.com", "password": "wrong"},
                format="json",
            )

        # Even with the correct password, lockout should now block.
        response = self.client.post(
            self.login_url,
            {"email": "owner@example.com", "password": self.password},
            format="json",
        )
        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert "locked" in response.json()["detail"].lower()

    def test_refresh_endpoint_issues_new_access_token(self):
        login_resp = self.client.post(
            self.login_url,
            {"email": "owner@example.com", "password": self.password},
            format="json",
        )
        refresh_token = login_resp.json()["refresh"]

        refresh_resp = self.client.post(
            reverse("accounts:refresh"),
            {"refresh": refresh_token},
            format="json",
        )
        assert refresh_resp.status_code == status.HTTP_200_OK
        assert "access" in refresh_resp.json()

    def test_me_endpoint_requires_auth(self):
        response = self.client.get(reverse("accounts:me"))
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_me_endpoint_returns_current_user(self):
        login_resp = self.client.post(
            self.login_url,
            {"email": "owner@example.com", "password": self.password},
            format="json",
        )
        access = login_resp.json()["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        response = self.client.get(reverse("accounts:me"))
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["email"] == "owner@example.com"

    def test_logout_blacklists_refresh_token(self):
        login_resp = self.client.post(
            self.login_url,
            {"email": "owner@example.com", "password": self.password},
            format="json",
        )
        access = login_resp.json()["access"]
        refresh = login_resp.json()["refresh"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        logout_resp = self.client.post(
            reverse("accounts:logout"),
            {"refresh": refresh},
            format="json",
        )
        assert logout_resp.status_code == status.HTTP_205_RESET_CONTENT

        # Refresh with blacklisted token should now fail.
        self.client.credentials()
        refresh_resp = self.client.post(
            reverse("accounts:refresh"),
            {"refresh": refresh},
            format="json",
        )
        assert refresh_resp.status_code == status.HTTP_401_UNAUTHORIZED
