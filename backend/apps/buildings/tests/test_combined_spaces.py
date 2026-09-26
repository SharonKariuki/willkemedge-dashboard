"""Combined commercial spaces: several units let as one."""
import datetime as dt
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.accounts.models import FinancialAuditLog, User
from apps.buildings.models import Building, Unit, UnitClassification, UnitStatus
from apps.buildings.spaces import reconfigure_space
from apps.payments.matching import match_tenant
from apps.payments.statement_service import _unit_descriptor
from apps.tenants.models import Tenant, TenantStatus
from apps.tenants.serializers import TenantCreateSerializer
from apps.tenants.services import move_out_tenant

pytestmark = pytest.mark.django_db


@pytest.fixture
def matasia():
    return Building.objects.create(name="Matasia Commercial", code="MC")


def _unit(building, label, rent, status=UnitStatus.VACANT, cls=UnitClassification.BUSINESS, floor=0):
    return Unit.objects.create(
        building=building, label=label, unit_type="shop", classification=cls,
        monthly_rent=Decimal(rent), status=status, floor=floor,
    )


@pytest.fixture
def hospital(matasia):
    """Sidai's hospital on MCG05, with MCG06-MCG08 vacant in the same building."""
    head = _unit(matasia, "MCG05", "86500", status=UnitStatus.OCCUPIED_PAID)
    tenant = Tenant.objects.create(
        first_name="Sidai Lonestar", last_name="Healthcare", id_number="PENDING-MCG05",
        phone="+254722301981", unit=head, monthly_rent=Decimal("86500"),
        move_in_date=dt.date(2026, 7, 1), status=TenantStatus.ACTIVE,
    )
    others = [_unit(matasia, f"MCG0{n}", "15000") for n in (6, 7, 8)]
    return head, tenant, others


def test_combining_moves_rent_by_the_units_standing_rent(hospital):
    head, tenant, (g06, g07, _g08) = hospital

    change = reconfigure_space(head, add=[g06, g07])

    tenant.refresh_from_db()
    assert tenant.monthly_rent == Decimal("116500")  # 86,500 + 2 x 15,000
    assert change.old_rent == Decimal("86500")
    assert head.space_label == "MCG05 + MCG06 + MCG07"
    g06.refresh_from_db()
    assert g06.combined_into == head
    assert g06.status == UnitStatus.OCCUPIED_PAID  # let with the head


def test_units_need_not_be_next_to_each_other_or_on_one_floor(hospital, matasia):
    head, tenant, (_g06, _g07, g08) = hospital
    upstairs = _unit(matasia, "MCF12", "50655", floor=1)

    reconfigure_space(head, add=[g08, upstairs])  # skips MCG06/MCG07, spans floors

    tenant.refresh_from_db()
    assert head.space_label == "MCG05 + MCF12 + MCG08"  # head first, then by label
    assert tenant.monthly_rent == Decimal("152155")  # 86,500 + 15,000 + 50,655


def test_agreed_rent_overrides_the_suggestion(hospital):
    head, tenant, (g06, *_rest) = hospital
    reconfigure_space(head, add=[g06], monthly_rent=Decimal("95000"))
    tenant.refresh_from_db()
    assert tenant.monthly_rent == Decimal("95000")


def test_shrinking_frees_the_unit_and_drops_its_rent(hospital):
    head, tenant, (g06, g07, _g08) = hospital
    reconfigure_space(head, add=[g06, g07])

    reconfigure_space(head, remove=[g07])

    tenant.refresh_from_db()
    g07.refresh_from_db()
    assert tenant.monthly_rent == Decimal("101500")
    assert g07.combined_into is None
    assert g07.status == UnitStatus.VACANT
    assert head.space_label == "MCG05 + MCG06"


def test_change_is_audited(hospital):
    head, tenant, (g06, *_rest) = hospital
    reconfigure_space(head, add=[g06])
    row = FinancialAuditLog.objects.get(action="unit.space_reconfigure")
    assert row.object_id == tenant.pk
    assert row.old_values == {"space": "MCG05", "monthly_rent": "86500.00"}
    assert row.new_values == {"space": "MCG05 + MCG06", "monthly_rent": "101500.00"}


def test_head_status_carries_to_the_whole_space(hospital):
    head, _tenant, (g06, *_rest) = hospital
    reconfigure_space(head, add=[g06])

    head.status = UnitStatus.ARREARS
    head.save(update_fields=["status", "updated_at"])

    g06.refresh_from_db()
    assert g06.status == UnitStatus.ARREARS


def test_move_out_vacates_the_space_but_keeps_it_combined(hospital):
    head, tenant, (g06, *_rest) = hospital
    reconfigure_space(head, add=[g06])

    move_out_tenant(tenant, dt.date(2026, 9, 30))

    g06.refresh_from_db()
    assert g06.status == UnitStatus.VACANT
    assert g06.combined_into == head


@pytest.mark.parametrize("problem", ["occupied", "other_building", "residential", "in_other_space"])
def test_refuses_units_that_cannot_join(hospital, matasia, problem):
    head, tenant, (g06, g07, g08) = hospital
    if problem == "occupied":
        g06.status = UnitStatus.OCCUPIED_UNPAID
        g06.save()
        Tenant.objects.create(
            first_name="Other", last_name="Shop", id_number="X1", phone="+254700000001",
            unit=g06, monthly_rent=Decimal("15000"), move_in_date=dt.date(2026, 7, 1),
        )
        target = g06
    elif problem == "other_building":
        target = _unit(Building.objects.create(name="Donholm", code="DON"), "DON9A", "9000")
    elif problem == "residential":
        target = _unit(matasia, "MCX01", "9000", cls=UnitClassification.RESIDENTIAL)
    else:
        reconfigure_space(g07, add=[g08])
        target = g08

    with pytest.raises(ValidationError):
        reconfigure_space(head, add=[target])
    tenant.refresh_from_db()
    assert tenant.monthly_rent == Decimal("86500")


def test_a_payment_quoting_any_unit_in_the_space_reaches_the_tenant(hospital):
    head, tenant, (g06, *_rest) = hospital
    reconfigure_space(head, add=[g06])
    assert match_tenant("90290#MCG06") == tenant
    assert match_tenant("90290#MCG05") == tenant


def test_a_unit_in_a_space_cannot_be_let_on_its_own(hospital):
    head, tenant, (g06, *_rest) = hospital
    reconfigure_space(head, add=[g06])
    move_out_tenant(tenant, dt.date(2026, 9, 30))  # space is vacant again

    ser = TenantCreateSerializer(data={
        "first_name": "A", "last_name": "B", "id_number": "NEW1", "phone": "+254700000002",
        "unit": g06.pk, "monthly_rent": "15000", "move_in_date": "2026-10-01",
    })
    assert not ser.is_valid()
    assert "combined space" in str(ser.errors["unit"])


def test_statement_names_every_unit_in_the_space(hospital):
    head, tenant, (g06, *_rest) = hospital
    reconfigure_space(head, add=[g06])
    tenant.refresh_from_db()
    assert _unit_descriptor(tenant) == "Units MCG05 + MCG06 — Matasia Commercial"


def test_api_reconfigures_for_record_money_roles_only(hospital):
    head, tenant, (g06, g07, _g08) = hospital
    url = f"/api/units/{head.pk}/reconfigure-space/"

    viewer = User.objects.create_user(username="caretaker", email="ct@test.com", password="pass12345!", role="caretaker")
    client = APIClient()
    client.force_authenticate(user=viewer)
    assert client.post(url, {"add": [g06.pk]}, format="json").status_code == 403

    owner = User.objects.create_user(username="osoro", email="osoro@test.com", password="pass12345!", role="owner")
    client.force_authenticate(user=owner)
    resp = client.post(url, {"add": [g06.pk, g07.pk], "monthly_rent": "110000"}, format="json")
    assert resp.status_code == 200, resp.data
    assert resp.data["space_label"] == "MCG05 + MCG06 + MCG07"
    assert [u["label"] for u in resp.data["combined_units"]] == ["MCG06", "MCG07"]
    tenant.refresh_from_db()
    assert tenant.monthly_rent == Decimal("110000")

    bad = client.post(url, {"remove": [_g08.pk]}, format="json")
    assert bad.status_code == 400
    assert "not part of" in bad.data["detail"]

    member = client.get(f"/api/units/{g06.pk}/").data
    assert member["combined_into_label"] == "MCG05"
    assert member["current_tenant_id"] == tenant.pk
