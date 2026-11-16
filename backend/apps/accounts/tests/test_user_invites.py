"""Invite-only accounts, managed by the owner and the superadmin.

Nobody signs up. The owner or superadmin invites by email with a role; the
person opens a single-use link and chooses their own password. The owner can
give any role but owner; switching an account off works at once.
"""
from datetime import timedelta
from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import AccountInvite, AuditLog, Role

User = get_user_model()
USERS = "/api/auth/users/"
ACCEPT = "/api/auth/invite/accept/"
PASSWORD = "Rent-roll-2026!"


def _user(email, role=Role.VIEWER, superuser=False):
    maker = User.objects.create_superuser if superuser else User.objects.create_user
    return maker(username=email, email=email, password=PASSWORD, role=role)


def _client(user=None):
    c = APIClient()
    if user:
        c.force_authenticate(user=user)
    return c


@pytest.fixture(autouse=True)
def emails():
    with mock.patch("apps.accounts.tasks.deliver_invite_email") as send:
        yield send


@pytest.fixture
def superadmin(db):
    return _user("sharon@example.com", superuser=True)


@pytest.fixture
def owner(db):
    return _user("osoro@example.com", Role.OWNER)


def _invite(actor, email="jane@example.com", role=Role.CARETAKER):
    from apps.buildings.models import Building

    payload = {"email": email, "role": role, "first_name": "Jane"}
    if role == Role.CARETAKER:
        # A caretaker looks after named buildings; the API refuses one without.
        building, _ = Building.objects.get_or_create(name="Block A", defaults={"address": "Nairobi"})
        payload["buildings"] = [building.pk]
    return _client(actor).post(USERS, payload, format="json")


# ── inviting ────────────────────────────────────────────────────────────────

def test_owner_invites_a_caretaker(owner, emails, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        resp = _invite(owner)
    assert resp.status_code == 201, resp.data
    assert resp.data["status"] == "invited" and resp.data["role"] == Role.CARETAKER

    jane = User.objects.get(email="jane@example.com")
    assert not jane.is_active and not jane.has_usable_password()
    assert jane.invited_by == owner
    link = AccountInvite.objects.get(user=jane)
    emails.assert_called_once()
    assert emails.call_args.args[0].pk == link.pk
    assert resp.data["email_error"] is None
    assert AuditLog.objects.filter(action="user.invite", object_id=jane.pk).exists()


def test_invited_person_cannot_sign_in_yet(owner):
    _invite(owner)
    resp = _client().post("/api/auth/login/", {"email": "jane@example.com", "password": PASSWORD}, format="json")
    assert resp.status_code == 400


def test_only_owner_and_superadmin_manage_users(db):
    for role in (Role.ACCOUNTANT, Role.CARETAKER, Role.VIEWER):
        someone = _user(f"{role}@example.com", role)
        assert _client(someone).get(USERS).status_code == 403
        assert _invite(someone).status_code == 403
    assert _client().get(USERS).status_code == 401


def test_owner_cannot_make_another_owner_but_superadmin_can(owner, superadmin):
    assert _invite(owner, role=Role.OWNER).status_code == 403
    assert _invite(superadmin, role=Role.OWNER).status_code == 201


def test_list_offers_only_the_roles_the_caller_may_give(owner, superadmin):
    owner_roles = [r["value"] for r in _client(owner).get(USERS).data["assignable_roles"]]
    super_roles = [r["value"] for r in _client(superadmin).get(USERS).data["assignable_roles"]]
    assert Role.OWNER not in owner_roles and Role.CARETAKER in owner_roles
    assert Role.OWNER in super_roles


def test_an_email_can_only_be_invited_once(owner):
    _invite(owner)
    resp = _invite(owner, email="JANE@example.com")
    assert resp.status_code == 400 and "Resend" in resp.data["detail"]
    assert _invite(owner, email=owner.email).status_code == 400


# ── accepting ───────────────────────────────────────────────────────────────

def _link(email="jane@example.com"):
    return AccountInvite.objects.filter(user__email=email, used=False).latest("created_at")


def test_accepting_sets_the_password_and_switches_the_account_on(owner):
    _invite(owner)
    token = _link().token

    shown = _client().get(f"/api/auth/invite/{token}/")
    assert shown.status_code == 200 and shown.data["email"] == "jane@example.com"

    resp = _client().post(ACCEPT, {"token": token, "new_password": PASSWORD}, format="json")
    assert resp.status_code == 200, resp.data
    jane = User.objects.get(email="jane@example.com")
    assert jane.is_active and jane.check_password(PASSWORD) and jane.status == "active"

    login = _client().post("/api/auth/login/", {"email": "jane@example.com", "password": PASSWORD}, format="json")
    assert login.status_code == 200
    # The link is single-use.
    again = _client().post(ACCEPT, {"token": token, "new_password": "Another-pass-2026!"}, format="json")
    assert again.status_code == 400
    assert _client().get(f"/api/auth/invite/{token}/").status_code == 404


def test_an_expired_link_is_refused(owner):
    _invite(owner)
    link = _link()
    AccountInvite.objects.filter(pk=link.pk).update(created_at=timezone.now() - timedelta(hours=73))
    resp = _client().post(ACCEPT, {"token": link.token, "new_password": PASSWORD}, format="json")
    assert resp.status_code == 400
    assert not User.objects.get(email="jane@example.com").is_active


def test_a_weak_password_is_refused(owner):
    _invite(owner)
    resp = _client().post(ACCEPT, {"token": _link().token, "new_password": "password1234"}, format="json")
    assert resp.status_code == 400
    assert not User.objects.get(email="jane@example.com").is_active


def test_resending_retires_the_old_link(owner, emails):
    _invite(owner)
    old = _link().token
    jane = User.objects.get(email="jane@example.com")
    assert _client(owner).post(f"{USERS}{jane.pk}/resend/").status_code == 200
    assert _client().get(f"/api/auth/invite/{old}/").status_code == 404
    assert _client().get(f"/api/auth/invite/{_link().token}/").status_code == 200


# ── changing and switching off ──────────────────────────────────────────────

def test_owner_changes_a_role(owner):
    accountant = _user("acc@example.com", Role.ACCOUNTANT)
    resp = _client(owner).patch(f"{USERS}{accountant.pk}/", {"role": Role.VIEWER}, format="json")
    assert resp.status_code == 200 and resp.data["role"] == Role.VIEWER
    assert AuditLog.objects.filter(action="user.update", object_id=accountant.pk).exists()


def test_nobody_changes_their_own_account_here(owner, superadmin):
    assert _client(owner).patch(f"{USERS}{owner.pk}/", {"role": Role.VIEWER}, format="json").status_code == 403
    assert _client(superadmin).post(f"{USERS}{superadmin.pk}/deactivate/").status_code == 403


def test_owner_cannot_touch_the_superadmin_or_another_owner(owner, superadmin):
    other_owner = _user("co-director@example.com", Role.OWNER)
    for target in (superadmin, other_owner):
        assert _client(owner).post(f"{USERS}{target.pk}/deactivate/").status_code == 403
        assert _client(owner).patch(f"{USERS}{target.pk}/", {"role": Role.VIEWER}, format="json").status_code == 403
    assert _client(superadmin).post(f"{USERS}{other_owner.pk}/deactivate/").status_code == 200


def test_switching_off_is_immediate_and_reversible(owner):
    from rest_framework_simplejwt.tokens import RefreshToken

    clerk = _user("clerk@example.com", Role.ACCOUNTANT)
    refresh = RefreshToken.for_user(clerk)
    session = APIClient()
    session.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    assert session.get("/api/auth/me/").status_code == 200

    resp = _client(owner).post(f"{USERS}{clerk.pk}/deactivate/")
    assert resp.status_code == 200 and resp.data["status"] == "deactivated"
    # The access token they already hold stops working, and so does refreshing.
    assert session.get("/api/auth/me/").status_code == 401
    assert _client().post("/api/auth/refresh/", {"refresh": str(refresh)}, format="json").status_code == 401
    login = _client().post("/api/auth/login/", {"email": clerk.email, "password": PASSWORD}, format="json")
    assert login.status_code == 400

    assert _client(owner).post(f"{USERS}{clerk.pk}/reactivate/").data["status"] == "active"
    login = _client().post("/api/auth/login/", {"email": clerk.email, "password": PASSWORD}, format="json")
    assert login.status_code == 200


def test_switching_off_an_invite_kills_its_link(owner):
    _invite(owner)
    token = _link().token
    jane = User.objects.get(email="jane@example.com")
    _client(owner).post(f"{USERS}{jane.pk}/deactivate/")
    assert _client().post(ACCEPT, {"token": token, "new_password": PASSWORD}, format="json").status_code == 400


def test_an_unknown_action_is_not_found(owner):
    clerk = _user("clerk@example.com", Role.ACCOUNTANT)
    assert _client(owner).post(f"{USERS}{clerk.pk}/delete/").status_code == 404


def test_me_says_who_may_manage_users(owner):
    assert _client(owner).get("/api/auth/me/").data["can_manage_users"] is True
    clerk = _user("clerk@example.com", Role.ACCOUNTANT)
    assert _client(clerk).get("/api/auth/me/").data["can_manage_users"] is False
