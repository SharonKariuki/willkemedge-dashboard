"""What each role may reach, enforced on every request.

These sign in with real JWTs: DRF's ``force_authenticate`` skips the
authentication classes, and the policy lives in one of them.

    caretaker  their buildings' buildings, units, tenants, maintenance and
               water readings - nothing financial, nothing elsewhere
    viewer     reads everything, changes nothing
    auditor    reads everything and the activity log, until an end date
    accountant reads and records money, manages properties
"""
import datetime as dt
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts import access
from apps.accounts.models import AuditLog, Role
from apps.buildings.models import Building, MaintenanceRequest, Unit, UnitClassification, UnitStatus
from apps.tenants.models import Tenant, TenantStatus

User = get_user_model()
PASSWORD = "Rent-roll-2026!"


@pytest.fixture
def estate(db):
    """Two buildings, a unit and a tenant in each."""
    out = {}
    for name, label in (("Donholm Estate", "D14"), ("Matasia Residential", "MR203")):
        b = Building.objects.create(name=name, address="Nairobi")
        u = Unit.objects.create(building=b, label=label, monthly_rent=Decimal("10000"),
                                classification=UnitClassification.RESIDENTIAL, status=UnitStatus.OCCUPIED_PAID)
        t = Tenant.objects.create(first_name="T", last_name=label, id_number=f"ID-{label}", phone="254700000000",
                                  unit=u, monthly_rent=Decimal("10000"), move_in_date=dt.date(2026, 1, 1),
                                  status=TenantStatus.ACTIVE)
        out[label] = (b, u, t)
    return out


def _person(role, buildings=(), expires=None, superuser=False):
    email = f"{role}{'-su' if superuser else ''}@example.com"
    maker = User.objects.create_superuser if superuser else User.objects.create_user
    user = maker(username=email, email=email, password=PASSWORD, role=role)
    user.access_expires_on = expires
    user.save()
    user.buildings.set(buildings)
    return user


def _signed_in(user):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


def _ids(resp):
    data = resp.data["results"] if isinstance(resp.data, dict) and "results" in resp.data else resp.data
    return sorted(row["id"] for row in data)


# ── caretaker ───────────────────────────────────────────────────────────────

def test_caretaker_sees_only_their_buildings(estate):
    donholm, d_unit, d_tenant = estate["D14"]
    caretaker = _person(Role.CARETAKER, [donholm])
    c = _signed_in(caretaker)

    assert _ids(c.get("/api/buildings/")) == [donholm.pk]
    assert _ids(c.get("/api/units/")) == [d_unit.pk]
    assert _ids(c.get("/api/tenants/")) == [d_tenant.pk]
    # Another building's records are not there at all.
    _, m_unit, m_tenant = estate["MR203"]
    assert c.get(f"/api/tenants/{m_tenant.pk}/").status_code == 404
    assert c.get(f"/api/units/{m_unit.pk}/").status_code == 404


def test_caretaker_has_no_financial_records(estate):
    donholm, _, d_tenant = estate["D14"]
    c = _signed_in(_person(Role.CARETAKER, [donholm]))
    for url in ("/api/payments/", "/api/dashboard/summary/", "/api/reports/arrears/",
                "/api/expenses/", "/api/reports/accounting/", f"/api/tenants/{d_tenant.pk}/payment-history/",
                "/api/notifications/", "/api/auth/activity/", "/api/auth/users/"):
        assert c.get(url).status_code == 403, url


def test_caretaker_cannot_change_tenants_or_units(estate):
    donholm, d_unit, d_tenant = estate["D14"]
    c = _signed_in(_person(Role.CARETAKER, [donholm]))
    assert c.patch(f"/api/tenants/{d_tenant.pk}/", {"phone": "254711111111"}, format="json").status_code == 403
    assert c.patch(f"/api/units/{d_unit.pk}/", {"monthly_rent": "1"}, format="json").status_code == 403


def test_caretaker_logs_maintenance_in_their_buildings_but_not_its_cost(estate):
    donholm, d_unit, _ = estate["D14"]
    _, m_unit, _ = estate["MR203"]
    c = _signed_in(_person(Role.CARETAKER, [donholm]))
    body = {"unit": d_unit.pk, "description": "Leaking tap", "reported_date": "2026-11-15"}
    assert c.post("/api/maintenance/", body, format="json").status_code == 201
    assert c.post("/api/maintenance/", {**body, "unit": m_unit.pk}, format="json").status_code == 403
    assert c.post("/api/maintenance/", {**body, "cost": "2500"}, format="json").status_code == 403
    assert MaintenanceRequest.objects.count() == 1


def test_caretaker_reads_water_only_in_their_buildings(estate):
    donholm, _, d_tenant = estate["D14"]
    _, _, m_tenant = estate["MR203"]
    c = _signed_in(_person(Role.CARETAKER, [donholm]))
    assert c.get("/api/utility-charges/previous-reading/", {"tenant": d_tenant.pk}).status_code == 200
    assert c.get("/api/utility-charges/previous-reading/", {"tenant": m_tenant.pk}).status_code == 404
    assert c.get("/api/utility-charges/").status_code == 200
    # Adding a charge is money, not a meter reading.
    assert c.post("/api/utility-charges/", {}, format="json").status_code == 403


def test_a_caretaker_with_no_buildings_sees_nothing(estate):
    c = _signed_in(_person(Role.CARETAKER))
    assert _ids(c.get("/api/buildings/")) == []
    assert _ids(c.get("/api/tenants/")) == []


# ── read-only roles ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("role", [Role.VIEWER, Role.AUDITOR])
def test_read_only_roles_read_everything_and_change_nothing(estate, role):
    expires = timezone.localdate() + dt.timedelta(days=30) if role == Role.AUDITOR else None
    c = _signed_in(_person(role, expires=expires))
    _, d_unit, d_tenant = estate["D14"]
    assert len(_ids(c.get("/api/tenants/"))) == 2
    for url in ("/api/payments/", "/api/dashboard/summary/", "/api/expenses/", "/api/reports/arrears/"):
        assert c.get(url).status_code == 200, url
    assert c.patch(f"/api/tenants/{d_tenant.pk}/", {"phone": "254711111111"}, format="json").status_code == 403
    assert c.post("/api/expenses/", {}, format="json").status_code == 403
    assert c.post("/api/payments/", {}, format="json").status_code == 403
    # Downloading a report is reading it, even though it is a POST.
    export = {"format": "csv", "title": "T", "columns": [{"key": "a", "label": "A"}], "rows": [{"a": "x"}]}
    assert c.post("/api/reports/export/", export, format="json").status_code == 200


def test_only_the_auditor_of_the_read_only_roles_sees_the_activity_log(estate):
    expires = timezone.localdate() + dt.timedelta(days=30)
    assert _signed_in(_person(Role.AUDITOR, expires=expires)).get("/api/auth/activity/").status_code == 200
    assert _signed_in(_person(Role.VIEWER)).get("/api/auth/activity/").status_code == 403


def test_access_ends_on_the_end_date(estate):
    auditor = _person(Role.AUDITOR, expires=timezone.localdate() + dt.timedelta(days=1))
    session = _signed_in(auditor)
    assert session.get("/api/tenants/").status_code == 200

    auditor.access_expires_on = timezone.localdate()
    auditor.save(update_fields=["access_expires_on"])
    assert session.get("/api/tenants/").status_code == 401
    login = APIClient().post("/api/auth/login/", {"email": auditor.email, "password": PASSWORD}, format="json")
    assert login.status_code == 400 and "access has ended" in str(login.data)


# ── full roles ──────────────────────────────────────────────────────────────

def test_accountant_records_money_and_manages_properties(estate):
    c = _signed_in(_person(Role.ACCOUNTANT))
    _, d_unit, d_tenant = estate["D14"]
    assert c.patch(f"/api/tenants/{d_tenant.pk}/", {"phone": "254711111111"}, format="json").status_code == 200
    assert c.get("/api/auth/activity/").status_code == 403
    assert c.get("/api/auth/users/").status_code == 403


@pytest.mark.parametrize("who", ["owner", "superadmin"])
def test_owner_and_superadmin_reach_everything(estate, who):
    user = _person(Role.OWNER) if who == "owner" else _person(Role.VIEWER, superuser=True)
    c = _signed_in(user)
    for url in ("/api/payments/", "/api/auth/activity/", "/api/auth/users/", "/api/tenants/"):
        assert c.get(url).status_code == 200, url
    assert len(_ids(c.get("/api/buildings/"))) == 2


# ── the policy itself ───────────────────────────────────────────────────────

def test_a_route_nobody_listed_is_treated_as_financial():
    assert access.required_capability("/api/some-new-thing/", "GET") == access.Cap.VIEW_FINANCE
    assert access.required_capability("/api/some-new-thing/", "POST") == access.Cap.RECORD_MONEY


def test_every_role_has_a_capability_set():
    assert set(access.ROLE_CAPABILITIES) == set(Role.values)


def test_a_refusal_is_logged_against_the_person(estate):
    donholm, _, d_tenant = estate["D14"]
    caretaker = _person(Role.CARETAKER, [donholm])
    _signed_in(caretaker).post("/api/expenses/", {}, format="json")
    row = AuditLog.objects.filter(kind="denied").latest("created_at")
    assert row.actor == caretaker and "/api/expenses/" in row.object_label


def test_me_tells_the_browser_what_the_person_may_do(estate):
    donholm, _, _ = estate["D14"]
    me = _signed_in(_person(Role.CARETAKER, [donholm])).get("/api/auth/me/").data
    assert set(me["capabilities"]) == set(access.ROLE_CAPABILITIES["caretaker"])
    assert me["buildings"] == [{"id": donholm.pk, "name": "Donholm Estate"}]
