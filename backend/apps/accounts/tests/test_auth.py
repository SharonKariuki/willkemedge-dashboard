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
            email="william@gmail.com",
            password=cls.password,
        )

    def setUp(self):
        self.client = APIClient()
        self.login_url = reverse("accounts:login")

    def test_login_success_returns_tokens_and_user(self):
        response = self.client.post(
            self.login_url,
            {"email": "william@gmail.com", "password": self.password},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert "access" in body and "refresh" in body
        assert body["user"]["email"] == "william@gmail.com"

    def test_login_returns_the_money_permissions_the_dashboard_gates_on(self):
        """Login and /auth/me/ must agree, or the UI gates on a field that
        only appears after a page refresh."""
        response = self.client.post(
            self.login_url,
            {"email": "william@gmail.com", "password": self.password},
            format="json",
        )
        user = response.json()["user"]
        assert user["role"] == "viewer"
        assert user["can_record_money"] is False
        assert user["can_forgive_money"] is False

    def test_owner_may_forgive_money(self):
        self.user.role = "owner"
        self.user.save(update_fields=["role"])
        response = self.client.post(
            self.login_url,
            {"email": "william@gmail.com", "password": self.password},
            format="json",
        )
        assert response.json()["user"]["can_forgive_money"] is True

    def test_login_success_records_audit_row(self):
        self.client.post(
            self.login_url,
            {"email": "william@gmail.com", "password": self.password},
            format="json",
        )
        attempt = LoginAttempt.objects.latest("attempted_at")
        assert attempt.email == "william@gmail.com"
        assert attempt.successful is True

    def test_login_email_is_case_insensitive(self):
        response = self.client.post(
            self.login_url,
            {"email": "WILLIAM@gmail.com", "password": self.password},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK

    def test_login_wrong_password_returns_400_and_audits(self):
        response = self.client.post(
            self.login_url,
            {"email": "william@gmail.com", "password": "wrong"},
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
                {"email": "william@gmail.com", "password": "wrong"},
                format="json",
            )

        # Even with the correct password, lockout should now block.
        response = self.client.post(
            self.login_url,
            {"email": "william@gmail.com", "password": self.password},
            format="json",
        )
        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert "locked" in response.json()["detail"].lower()

    def test_lockout_is_ip_scoped_to_prevent_dos(self):
        """An attacker at one IP must not be able to lock the owner out globally."""
        attacker_ip = "203.0.113.10"
        for _ in range(LOCKOUT_THRESHOLD):
            self.client.post(
                self.login_url,
                {"email": "william@gmail.com", "password": "wrong"},
                format="json",
                REMOTE_ADDR=attacker_ip,
            )

        # The attacker's own IP is locked for that email...
        blocked = self.client.post(
            self.login_url,
            {"email": "william@gmail.com", "password": self.password},
            format="json",
            REMOTE_ADDR=attacker_ip,
        )
        assert blocked.status_code == status.HTTP_429_TOO_MANY_REQUESTS

        # ...but the real owner signing in from a different IP is unaffected.
        ok = self.client.post(
            self.login_url,
            {"email": "william@gmail.com", "password": self.password},
            format="json",
            REMOTE_ADDR="198.51.100.7",
        )
        assert ok.status_code == status.HTTP_200_OK

    def test_successful_login_resets_failed_attempt_window(self):
        # A few failed attempts (below threshold)...
        for _ in range(LOCKOUT_THRESHOLD - 1):
            self.client.post(
                self.login_url,
                {"email": "william@gmail.com", "password": "wrong"},
                format="json",
            )
        assert LoginAttempt.objects.filter(
            email="william@gmail.com", successful=False
        ).count() == LOCKOUT_THRESHOLD - 1

        # ...then a success clears the in-window failures.
        ok = self.client.post(
            self.login_url,
            {"email": "william@gmail.com", "password": self.password},
            format="json",
        )
        assert ok.status_code == status.HTTP_200_OK
        assert LoginAttempt.objects.filter(
            email="william@gmail.com", successful=False
        ).count() == 0
        # The successful audit row survives.
        assert LoginAttempt.objects.filter(
            email="william@gmail.com", successful=True
        ).count() == 1

    def test_refresh_endpoint_issues_new_access_token(self):
        login_resp = self.client.post(
            self.login_url,
            {"email": "william@gmail.com", "password": self.password},
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
            {"email": "william@gmail.com", "password": self.password},
            format="json",
        )
        access = login_resp.json()["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        response = self.client.get(reverse("accounts:me"))
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["email"] == "william@gmail.com"

    def test_logout_blacklists_refresh_token(self):
        login_resp = self.client.post(
            self.login_url,
            {"email": "william@gmail.com", "password": self.password},
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
