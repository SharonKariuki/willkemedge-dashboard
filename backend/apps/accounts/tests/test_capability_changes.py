"""Per-person changes to a role: what they do, and who may make them.

    owner       may add anything they hold except "manage users" and "void and
                write off" - those two are the superadmin's to give
    superadmin  may add anything
    caretaker   can lose capabilities but never gain one (building scoping
                covers only the property side)

Requests sign in with real JWTs: the access policy runs in the
authentication class, which ``force_authenticate`` skips.
"""
import datetime as dt

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts import access
from apps.accounts.access import Cap
from apps.accounts.models import AuditLog, Role
from apps.buildings.models import Building

User = get_user_model()
USERS = "/api/auth/users/"


def _person(email, role, superuser=False, **fields):
    maker = User.objects.create_superuser if superuser else User.objects.create_user
    user = maker(username=email, email=email, password="Rent-roll-2026!", role=role)
    for k, v in fields.items():
        setattr(user, k, v)
    user.save()
    return user


def _signed_in(user):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


@pytest.fixture
def owner(db):
    return _person("osoro@example.com", Role.OWNER)


@pytest.fixture
def superadmin(db):
    return _person("sharon@example.com", Role.OWNER, superuser=True)


# ── the arithmetic ──────────────────────────────────────────────────────────

def test_taking_away_a_requirement_takes_what_depends_on_it():
    caps = access.effective(Role.ACCOUNTANT, removed=[Cap.VIEW_FINANCE])
    assert Cap.VIEW_FINANCE not in caps
    assert Cap.RECORD_MONEY not in caps and Cap.SEND_MESSAGES not in caps
    assert Cap.VIEW_PROPERTY in caps


def test_a_caretaker_gains_nothing_even_if_the_database_says_so():
    assert access.effective(Role.CARETAKER, added=[Cap.VIEW_FINANCE]) == access.ROLE_CAPABILITIES[Role.CARETAKER]


# ── through the API ─────────────────────────────────────────────────────────

def test_owner_lets_a_viewer_record_money(owner):
    viewer = _person("v@example.com", Role.VIEWER)
    assert _signed_in(viewer).post("/api/expenses/", {}, format="json").status_code == 403

    resp = _signed_in(owner).patch(f"{USERS}{viewer.pk}/", {"extra_capabilities": [Cap.RECORD_MONEY]}, format="json")
    assert resp.status_code == 200, resp.data
    assert resp.data["extra_capabilities"] == [Cap.RECORD_MONEY]
    assert Cap.RECORD_MONEY in resp.data["capabilities"]
    # Past the policy now: the view itself answers (the empty form is invalid).
    assert _signed_in(viewer).post("/api/expenses/", {}, format="json").status_code == 400


def test_taking_record_money_from_an_accountant_stops_it(owner):
    acc = _person("a@example.com", Role.ACCOUNTANT)
    resp = _signed_in(owner).patch(f"{USERS}{acc.pk}/", {"removed_capabilities": [Cap.RECORD_MONEY]}, format="json")
    assert resp.status_code == 200, resp.data
    assert _signed_in(acc).post("/api/expenses/", {}, format="json").status_code == 403
    assert Cap.RECORD_MONEY not in _signed_in(acc).get("/api/auth/me/").data["capabilities"]


@pytest.mark.parametrize("cap", [Cap.MANAGE_USERS, Cap.FORGIVE_MONEY])
def test_only_the_superadmin_gives_out_user_management_or_write_offs(owner, superadmin, cap):
    acc = _person("a@example.com", Role.ACCOUNTANT)
    refused = _signed_in(owner).patch(f"{USERS}{acc.pk}/", {"extra_capabilities": [cap]}, format="json")
    assert refused.status_code == 403
    assert "superadmin" in refused.data["detail"]

    ok = _signed_in(superadmin).patch(f"{USERS}{acc.pk}/", {"extra_capabilities": [cap]}, format="json")
    assert ok.status_code == 200 and ok.data["extra_capabilities"] == [cap]


def test_owner_can_change_other_things_without_undoing_a_superadmin_grant(owner):
    acc = _person("a@example.com", Role.ACCOUNTANT, extra_capabilities=[Cap.FORGIVE_MONEY])
    resp = _signed_in(owner).patch(
        f"{USERS}{acc.pk}/",
        {"extra_capabilities": [Cap.FORGIVE_MONEY, Cap.VIEW_ACTIVITY]},
        format="json",
    )
    assert resp.status_code == 200, resp.data
    assert resp.data["extra_capabilities"] == [Cap.FORGIVE_MONEY, Cap.VIEW_ACTIVITY]


def test_someone_managing_users_cannot_hand_out_what_they_lack(owner):
    manager = _person("m@example.com", Role.VIEWER, extra_capabilities=[Cap.MANAGE_USERS])
    viewer = _person("v@example.com", Role.VIEWER)
    resp = _signed_in(manager).patch(f"{USERS}{viewer.pk}/", {"extra_capabilities": [Cap.RECORD_MONEY]}, format="json")
    assert resp.status_code == 403


def test_a_caretaker_can_lose_permissions_but_not_gain_them(owner):
    block = Building.objects.create(name="Block A", address="Nairobi")
    ct = _person("c@example.com", Role.CARETAKER)
    ct.buildings.set([block])
    c = _signed_in(owner)

    refused = c.patch(f"{USERS}{ct.pk}/", {"extra_capabilities": [Cap.VIEW_FINANCE]}, format="json")
    assert refused.status_code == 400 and "caretaker" in refused.data["detail"]

    ok = c.patch(f"{USERS}{ct.pk}/", {"removed_capabilities": [Cap.RECORD_WATER]}, format="json")
    assert ok.status_code == 200 and Cap.RECORD_WATER not in ok.data["capabilities"]
    assert _signed_in(ct).get("/api/utility-charges/previous-reading/").status_code == 403


def test_a_new_role_starts_without_the_old_changes(owner):
    acc = _person("a@example.com", Role.ACCOUNTANT, removed_capabilities=[Cap.SEND_MESSAGES])
    resp = _signed_in(owner).patch(f"{USERS}{acc.pk}/", {"role": Role.VIEWER}, format="json")
    assert resp.status_code == 200
    assert resp.data["extra_capabilities"] == [] and resp.data["removed_capabilities"] == []


def test_changes_that_match_the_role_are_not_stored(owner):
    acc = _person("a@example.com", Role.ACCOUNTANT)
    resp = _signed_in(owner).patch(
        f"{USERS}{acc.pk}/",
        # Already in the role; and one that can't stand without "see the books".
        {"extra_capabilities": [Cap.RECORD_MONEY], "removed_capabilities": [Cap.VIEW_FINANCE]},
        format="json",
    )
    assert resp.status_code == 200
    assert resp.data["extra_capabilities"] == []
    assert set(resp.data["removed_capabilities"]) == {Cap.VIEW_FINANCE, Cap.RECORD_MONEY, Cap.SEND_MESSAGES}


def test_the_activity_log_says_what_changed(owner):
    viewer = _person("v@example.com", Role.VIEWER)
    _signed_in(owner).patch(f"{USERS}{viewer.pk}/", {"extra_capabilities": [Cap.VIEW_ACTIVITY]}, format="json")
    row = AuditLog.objects.get(action="user.update")
    assert row.summary == "Changed what v@example.com may do: + See the activity log"


def test_invite_with_changes_and_an_end_date_for_any_role(owner):
    resp = _signed_in(owner).post(USERS, {
        "email": "temp@example.com", "role": Role.ACCOUNTANT,
        "removed_capabilities": [Cap.SEND_MESSAGES],
        "access_expires_on": (dt.date.today() + dt.timedelta(days=30)).isoformat(),
    }, format="json")
    assert resp.status_code == 201, resp.data
    assert resp.data["removed_capabilities"] == [Cap.SEND_MESSAGES]
    assert resp.data["access_expires_on"]


def test_the_list_says_what_the_caller_may_grant(owner, superadmin):
    perms = {p["value"]: p for p in _signed_in(owner).get(USERS).data["permissions"]}
    assert perms[Cap.MANAGE_USERS]["grantable"] is False
    assert perms[Cap.RECORD_MONEY]["grantable"] is True
    assert perms[Cap.RECORD_MONEY]["requires"] == [Cap.VIEW_FINANCE]
    su = {p["value"]: p for p in _signed_in(superadmin).get(USERS).data["permissions"]}
    assert su[Cap.MANAGE_USERS]["grantable"] is True
