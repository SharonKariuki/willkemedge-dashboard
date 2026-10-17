"""A unit's status must agree with its tenancy, and rent changes must be safe.

Audit 12 Oct 2026: set-status could mark a let unit vacant (hiding the tenant
and letting a second one move in on top), adjust-rent crashed on bad input and
never said it leaves current tenants' billed rent alone, and nothing in the
database stopped two current tenants on one unit.
"""
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from rest_framework.test import APIClient

from apps.accounts.models import AuditLog
from apps.buildings.models import Building, Unit, UnitStatus
from apps.tenants.models import Tenant, TenantStatus

User = get_user_model()


@pytest.fixture
def client(db):
    c = APIClient()
    c.force_authenticate(User.objects.create_user(username="o", email="o@x.com", password="x", role="owner"))
    return c


@pytest.fixture
def building(db):
    return Building.objects.create(name="Road Block", total_floors=2)


def _unit(building, label, rent="10000", status=UnitStatus.VACANT):
    return Unit.objects.create(building=building, label=label, monthly_rent=Decimal(rent), status=status)


def _tenant(unit, id_number="T1", status=TenantStatus.ACTIVE, rent="10000"):
    return Tenant.objects.create(
        first_name="Amina", last_name="K", id_number=id_number, phone="+254700000001", unit=unit,
        monthly_rent=Decimal(rent), move_in_date="2026-01-01", status=status,
    )


def _set(client, unit, status):
    return client.patch(f"/api/units/{unit.id}/set-status/", {"status": status}, format="json")


# --- set-status ---------------------------------------------------------------

def test_a_let_unit_cannot_be_marked_vacant_or_under_maintenance(client, building):
    unit = _unit(building, "RB1", status=UnitStatus.OCCUPIED_PAID)
    _tenant(unit)
    for status in (UnitStatus.VACANT, UnitStatus.UNDER_MAINTENANCE):
        res = _set(client, unit, status)
        assert res.status_code == 400
        assert "Move them out first" in res.json()["detail"]
    unit.refresh_from_db()
    assert unit.status == UnitStatus.OCCUPIED_PAID


def test_an_empty_unit_cannot_be_marked_occupied(client, building):
    unit = _unit(building, "RB2")
    res = _set(client, unit, UnitStatus.OCCUPIED_PAID)
    assert res.status_code == 400
    assert "no current tenant" in res.json()["detail"]


def test_an_empty_unit_can_go_under_maintenance_and_back(client, building):
    unit = _unit(building, "RB3")
    assert _set(client, unit, UnitStatus.UNDER_MAINTENANCE).status_code == 200
    assert _set(client, unit, UnitStatus.VACANT).status_code == 200


def test_a_moved_out_tenant_does_not_count(client, building):
    unit = _unit(building, "RB4")
    _tenant(unit, status=TenantStatus.MOVED_OUT)
    assert _set(client, unit, UnitStatus.UNDER_MAINTENANCE).status_code == 200


def test_a_member_of_a_combined_space_follows_its_head(client, building):
    head = _unit(building, "MCG05")
    member = _unit(building, "MCG06")
    member.combined_into = head
    member.save(update_fields=["combined_into"])
    res = _set(client, member, UnitStatus.UNDER_MAINTENANCE)
    assert res.status_code == 400
    assert "MCG05" in res.json()["detail"]


# --- one current tenancy per unit --------------------------------------------

def test_the_database_refuses_a_second_current_tenant_on_a_unit(building):
    unit = _unit(building, "RB5", status=UnitStatus.OCCUPIED_PAID)
    _tenant(unit, id_number="T1")
    with pytest.raises(IntegrityError), transaction.atomic():
        _tenant(unit, id_number="T2")
    # A moved-out tenancy on the same unit is history, not a clash.
    _tenant(unit, id_number="T3", status=TenantStatus.MOVED_OUT)


# --- adjust-rent --------------------------------------------------------------

def _adjust(client, building, amount, kind="fixed"):
    return client.post(f"/api/buildings/{building.id}/adjust-rent/", {"amount": amount, "type": kind}, format="json")


def test_adjust_rent_changes_listed_rent_not_current_tenants_and_says_so(client, building):
    let = _unit(building, "RB6", rent="10000", status=UnitStatus.OCCUPIED_PAID)
    tenant = _tenant(let, rent="9500")
    empty = _unit(building, "RB7", rent="12000")

    res = _adjust(client, building, "10", "percent")
    assert res.status_code == 200
    assert res.json()["current_tenancies_unchanged"] == 1
    let.refresh_from_db()
    empty.refresh_from_db()
    tenant.refresh_from_db()
    assert let.monthly_rent == Decimal("11000")
    assert empty.monthly_rent == Decimal("13200")
    assert tenant.monthly_rent == Decimal("9500")  # the agreed rent is untouched
    assert AuditLog.objects.filter(action="building.adjust_rent").exists()


@pytest.mark.parametrize("amount,kind", [("abc", "fixed"), ("", "fixed"), ("0", "fixed"), ("-100", "percent"), ("150", "percent")])
def test_adjust_rent_rejects_bad_input_with_400(client, building, amount, kind):
    _unit(building, "RB8")
    assert _adjust(client, building, amount, kind).status_code == 400


def test_adjust_rent_refuses_to_make_any_rent_negative(client, building):
    _unit(building, "RB9", rent="20000")
    small = _unit(building, "RB10", rent="3000")
    res = _adjust(client, building, "-5000")
    assert res.status_code == 400
    assert "RB10" in res.json()["detail"]
    small.refresh_from_db()
    assert small.monthly_rent == Decimal("3000")  # nothing half-applied


# --- negative values through the API (audit #11) --------------------------------

def test_a_negative_rent_is_a_400_not_a_server_error(client, building):
    unit = _unit(building, "RB11")
    res = client.post("/api/tenants/", {
        "first_name": "Jane", "last_name": "W", "id_number": "N1", "phone": "+254712345678",
        "unit": unit.id, "monthly_rent": "-1", "move_in_date": "2026-04-01",
    }, format="json")
    assert res.status_code == 400

    tenant = _tenant(_unit(building, "RB12", status=UnitStatus.OCCUPIED_PAID), id_number="N2")
    res = client.patch(f"/api/tenants/{tenant.id}/", {"monthly_rent": "-1"}, format="json")
    assert res.status_code == 400
