"""The director's activity log: what is captured, from where, and who may read it."""
import datetime as dt
from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.accounts.audit_context import AuditContext, Source, bind
from apps.accounts.models import AuditLog, Role, User
from apps.buildings.models import Building, Unit, UnitStatus
from apps.payments.cron_views import _record_run
from apps.tenants.models import Tenant, TenantStatus

pytestmark = pytest.mark.django_db

PASSWORD = "CorrectHorseBattery9!"


def _user(email, role, first="", last=""):
    return User.objects.create_user(
        username=email.split("@")[0], email=email, password=PASSWORD,
        role=role, first_name=first, last_name=last,
    )


@pytest.fixture
def owner():
    return _user("osoro@example.com", Role.OWNER, "Dr", "Osoro")


@pytest.fixture
def unit():
    building = Building.objects.create(name="Road Block", code="RB")
    return Unit.objects.create(
        building=building, label="RBG01", unit_type="shop",
        monthly_rent=Decimal("25000"), status=UnitStatus.VACANT,
    )


def _signed_in(email):
    """A client signed in through the real login endpoint, and its session id."""
    client = APIClient()
    res = client.post(reverse("accounts:login"), {"email": email, "password": PASSWORD}, format="json")
    assert res.status_code == 200, res.content
    access = res.json()["access"]
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    return client, AccessToken(access)["sid"]


# ── what is captured ─────────────────────────────────────────────────────────

def test_a_rent_change_on_the_dashboard_names_who_what_and_which_sign_in(owner, unit):
    client, sid = _signed_in(owner.email)

    res = client.patch(f"/api/units/{unit.pk}/", {"monthly_rent": "22000"}, format="json", HTTP_USER_AGENT="Chrome/Android")
    assert res.status_code == 200, res.content

    row = AuditLog.objects.get(kind="change", action="unit.update")
    assert row.actor == owner and row.actor_label == "Dr Osoro" and row.actor_role == Role.OWNER
    assert row.summary == "Changed unit RBG01 — Monthly rent: 25,000.00 → 22,000.00"
    assert row.old_values == {"monthly_rent": "25000.00"}
    assert row.new_values == {"monthly_rent": "22000.00"}
    assert row.is_financial is True
    assert row.source == Source.WEB
    assert row.session_id == sid
    assert row.user_agent == "Chrome/Android"


def test_the_sign_in_itself_is_logged_under_the_same_session(owner):
    _client, sid = _signed_in(owner.email)

    login = AuditLog.objects.get(action="auth.login")
    assert login.kind == "auth" and login.actor == owner and login.session_id == sid


def test_a_failed_sign_in_is_kept_even_after_a_later_success_clears_the_lockout(owner):
    APIClient().post(reverse("accounts:login"), {"email": owner.email, "password": "wrong"}, format="json")
    _signed_in(owner.email)

    failed = AuditLog.objects.get(action="auth.login_failed")
    assert failed.actor is None and failed.object_label == owner.email


def test_saving_without_a_real_change_writes_nothing(unit):
    unit.monthly_rent = "25000"  # same figure, different type
    unit.save()
    assert not AuditLog.objects.filter(action="unit.update").exists()


def test_derived_unit_status_is_not_logged(unit):
    unit.status = UnitStatus.OCCUPIED_PAID
    unit.save(update_fields=["status", "updated_at"])
    assert not AuditLog.objects.filter(action="unit.update").exists()


def test_tenant_id_numbers_are_masked(unit):
    tenant = Tenant.objects.create(
        first_name="Jane", last_name="Wanjiru", id_number="12345678", phone="0700000000",
        unit=unit, monthly_rent=Decimal("25000"), move_in_date=dt.date(2026, 9, 1),
        status=TenantStatus.ACTIVE,
    )
    created = AuditLog.objects.get(action="tenant.create")
    assert created.new_values["id_number"] == "•••••678"
    assert created.summary.startswith("Added tenant Jane Wanjiru (RBG01)")

    tenant.id_number = "87654321"
    tenant.save()
    changed = AuditLog.objects.get(action="tenant.update")
    assert "12345678" not in changed.summary and "87654321" not in changed.summary
    assert changed.is_financial is False


def test_a_password_change_is_logged_without_the_hash(owner):
    owner.set_password("AnotherHorseBattery9!")
    owner.save()
    row = AuditLog.objects.get(action="user.update")
    assert row.summary == "Changed user account osoro@example.com — Password changed"
    assert row.old_values == {"password": "(hidden)"} and row.new_values == {"password": "(hidden)"}


def test_a_refused_change_is_logged():
    caretaker = _user("care@example.com", Role.CARETAKER)
    client, _sid = _signed_in(caretaker.email)

    res = client.post("/api/payments/999/void/", {"reason": "x"}, format="json")
    assert res.status_code == 403

    row = AuditLog.objects.get(kind="denied")
    assert row.actor == caretaker
    assert row.summary == "Refused: POST /api/payments/999/void/ (role: Caretaker)"


def test_a_server_command_announces_itself_once_before_its_changes(unit):
    ctx = AuditContext(source=Source.COMMAND, source_detail="fix_rents", argv=["fix_rents", "--apply"])
    with bind(ctx):
        unit.monthly_rent = Decimal("30000")
        unit.save()
        unit.monthly_rent = Decimal("31000")
        unit.save()

    rows = list(AuditLog.objects.filter(source=Source.COMMAND).order_by("id"))
    assert [r.action for r in rows] == ["command.run", "unit.update", "unit.update"]
    assert rows[0].summary == "Server command run: manage.py fix_rents --apply"
    assert len({r.request_id for r in rows}) == 1


def test_the_billing_run_is_summarised_not_listed_charge_by_charge():
    _record_run("monthly-arrears", 54)
    _record_run("monthly-arrears", 0)  # nothing raised, nothing to say

    row = AuditLog.objects.get()
    assert row.summary == "Monthly billing raised 54 rent charges"
    assert row.is_financial is True


# ── who may read it ──────────────────────────────────────────────────────────

URL = "/api/auth/activity/"


def test_only_the_owner_can_read_the_log(owner):
    accountant = _user("acc@example.com", Role.ACCOUNTANT)
    client, _ = _signed_in(accountant.email)
    assert client.get(URL).status_code == 403

    client, _ = _signed_in(owner.email)
    assert client.get(URL).status_code == 200


def test_filters_and_paging(owner, unit):
    unit.monthly_rent = Decimal("26000")
    unit.save()  # system, financial
    unit.notes = "Leaking tap"
    unit.save()  # system, not financial
    client, _ = _signed_in(owner.email)  # owner's sign-in row

    body = client.get(URL, {"financial": "1"}).json()
    assert [r["action"] for r in body["results"]] == ["unit.update", "unit.create"]
    assert "Monthly rent" in body["results"][0]["summary"]
    assert {p["label"] for p in body["people"]} == {"Dr Osoro"}

    body = client.get(URL, {"actor": "system", "object_type": "unit", "object_id": unit.pk}).json()
    assert len(body["results"]) == 3  # create + two updates

    body = client.get(URL, {"actor": owner.pk}).json()
    assert [r["action"] for r in body["results"]] == ["auth.login"]

    body = client.get(URL, {"q": "leaking"}).json()
    assert len(body["results"]) == 1

    first = client.get(URL, {"limit": 2}).json()
    assert len(first["results"]) == 2 and first["next_before"] is not None
    rest = client.get(URL, {"limit": 2, "before": first["next_before"]}).json()
    assert "people" not in rest
    ids = [r["id"] for r in first["results"] + rest["results"]]
    assert ids == sorted(ids, reverse=True) and len(set(ids)) == len(ids)


def test_bad_filter_values_are_a_400_not_a_500(owner):
    client, _ = _signed_in(owner.email)
    assert client.get(URL, {"date_from": "28/09/2026"}).status_code == 400
    assert client.get(URL, {"actor": "someone"}).status_code == 400
