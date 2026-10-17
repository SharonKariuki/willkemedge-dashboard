"""The two ways an account gets a new password from the application.

Both were dead in production: /api/auth/change-password/ was never routed
(404) and the reset-confirm page posted the wrong field name (400). These
tests pin the wire contract the frontend actually sends, so a rename on
either side fails here rather than in front of the director.
"""
import pytest
from django.contrib.auth import get_user_model

from apps.accounts.models import PasswordResetToken

User = get_user_model()

OLD_PASSWORD = "CurrentPass123!x"
NEW_PASSWORD = "BrandNewPass456!x"


@pytest.fixture
def owner(db):
    return User.objects.create_superuser(
        username="owner", email="owner@wilkem.test", password=OLD_PASSWORD, role="owner"
    )


def login(client, email, password):
    return client.post(
        "/api/auth/login/",
        {"email": email, "password": password},
        content_type="application/json",
    )


def auth(client, user):
    res = login(client, user.email, OLD_PASSWORD)
    assert res.status_code == 200
    return {"HTTP_AUTHORIZATION": f"Bearer {res.json()['access']}"}


@pytest.mark.django_db
class TestChangePassword:
    """POST /api/auth/change-password/ — the no-email route."""

    URL = "/api/auth/change-password/"

    def test_route_exists(self, owner, client):
        """It answered 404 before: the path was never added to urls.py."""
        res = client.post(self.URL, {}, content_type="application/json",
                          **auth(client, owner))
        assert res.status_code != 404

    def test_payload_the_settings_page_sends_is_accepted(self, owner, client):
        res = client.post(
            self.URL,
            {"current_password": OLD_PASSWORD, "new_password": NEW_PASSWORD},
            content_type="application/json",
            **auth(client, owner),
        )
        assert res.status_code == 200
        owner.refresh_from_db()
        assert owner.check_password(NEW_PASSWORD)

    def test_new_password_logs_in_and_old_one_does_not(self, owner, client):
        client.post(
            self.URL,
            {"current_password": OLD_PASSWORD, "new_password": NEW_PASSWORD},
            content_type="application/json",
            **auth(client, owner),
        )
        assert login(client, owner.email, NEW_PASSWORD).status_code == 200
        assert login(client, owner.email, OLD_PASSWORD).status_code == 400

    def test_caller_is_handed_a_working_token_pair(self, owner, client):
        res = client.post(
            self.URL,
            {"current_password": OLD_PASSWORD, "new_password": NEW_PASSWORD},
            content_type="application/json",
            **auth(client, owner),
        )
        body = res.json()
        assert body["access"] and body["refresh"]
        me = client.get("/api/auth/me/", HTTP_AUTHORIZATION=f"Bearer {body['access']}")
        assert me.status_code == 200

    def test_old_refresh_token_is_dead_afterwards(self, owner, client):
        res = login(client, owner.email, OLD_PASSWORD)
        stale_refresh = res.json()["refresh"]
        client.post(
            self.URL,
            {"current_password": OLD_PASSWORD, "new_password": NEW_PASSWORD},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {res.json()['access']}",
        )
        refreshed = client.post(
            "/api/auth/refresh/",
            {"refresh": stale_refresh},
            content_type="application/json",
        )
        assert refreshed.status_code == 401

    def test_wrong_current_password_is_refused(self, owner, client):
        res = client.post(
            self.URL,
            {"current_password": "not-it", "new_password": NEW_PASSWORD},
            content_type="application/json",
            **auth(client, owner),
        )
        assert res.status_code == 400
        owner.refresh_from_db()
        assert owner.check_password(OLD_PASSWORD)

    def test_anonymous_caller_is_refused(self, owner, client):
        res = client.post(
            self.URL,
            {"current_password": OLD_PASSWORD, "new_password": NEW_PASSWORD},
            content_type="application/json",
        )
        assert res.status_code == 401
        owner.refresh_from_db()
        assert owner.check_password(OLD_PASSWORD)

    def test_reusing_the_current_password_is_refused(self, owner, client):
        res = client.post(
            self.URL,
            {"current_password": OLD_PASSWORD, "new_password": OLD_PASSWORD},
            content_type="application/json",
            **auth(client, owner),
        )
        assert res.status_code == 400

    def test_short_password_is_refused_with_a_field_error(self, owner, client):
        res = client.post(
            self.URL,
            {"current_password": OLD_PASSWORD, "new_password": "Short1!"},
            content_type="application/json",
            **auth(client, owner),
        )
        assert res.status_code == 400
        # The Settings page reads these per-field messages, not `detail`.
        assert "new_password" in res.json()


@pytest.mark.django_db
class TestPasswordResetConfirmContract:
    """POST /api/auth/password-reset/confirm/ — the emailed break-glass route."""

    URL = "/api/auth/password-reset/confirm/"

    def token_for(self, user):
        return PasswordResetToken.create_for_user(user).token

    def test_payload_the_reset_page_sends_is_accepted(self, owner, client):
        """The page sent `password`; the serializer wants `new_password`.

        That single mismatch turned every real reset link into
        "Reset link is invalid or has expired."
        """
        res = client.post(
            self.URL,
            {"token": self.token_for(owner), "new_password": NEW_PASSWORD},
            content_type="application/json",
        )
        assert res.status_code == 200
        owner.refresh_from_db()
        assert owner.check_password(NEW_PASSWORD)

    def test_reset_password_logs_in(self, owner, client):
        client.post(
            self.URL,
            {"token": self.token_for(owner), "new_password": NEW_PASSWORD},
            content_type="application/json",
        )
        assert login(client, owner.email, NEW_PASSWORD).status_code == 200

    def test_token_is_single_use(self, owner, client):
        token = self.token_for(owner)
        body = {"token": token, "new_password": NEW_PASSWORD}
        assert client.post(self.URL, body, content_type="application/json").status_code == 200
        again = client.post(self.URL, body, content_type="application/json")
        assert again.status_code == 400

    def test_unknown_token_is_refused(self, owner, client):
        res = client.post(
            self.URL,
            {"token": "nope", "new_password": NEW_PASSWORD},
            content_type="application/json",
        )
        assert res.status_code == 400
        owner.refresh_from_db()
        assert owner.check_password(OLD_PASSWORD)


@pytest.mark.django_db
def test_reset_request_never_reveals_whether_an_account_exists(owner, client):
    known = client.post("/api/auth/password-reset/", {"email": owner.email},
                        content_type="application/json")
    unknown = client.post("/api/auth/password-reset/", {"email": "nobody@nowhere.test"},
                          content_type="application/json")
    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json()
