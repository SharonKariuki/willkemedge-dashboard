"""
The nightly status sweep must treat a tenant on notice as still in the unit.

MCF12 read Vacant on the units board from 22 Sept 2026, the night after Sidai
gave notice, while they were still in occupation and still being billed: the
sweep looked for an ACTIVE tenant only. Every other occupancy check counts
NOTICE_GIVEN as the current tenant, and so must this one.
"""
from decimal import Decimal

import pytest

from apps.buildings.models import Building, Unit, UnitClassification, UnitStatus
from apps.payments.tasks import recalculate_all_statuses
from apps.tenants.models import Tenant, TenantStatus

D = Decimal


@pytest.fixture
def arcade(db):
    return Building.objects.create(name="Matasia Arcade", code="MCW", total_floors=2)


def _unit(building, label, status=UnitStatus.OCCUPIED_UNPAID):
    return Unit.objects.create(
        building=building, label=label, monthly_rent=D("50655"),
        classification=UnitClassification.BUSINESS, status=status,
    )


def _tenant(unit, status):
    return Tenant.objects.create(
        first_name="Sidai", last_name=unit.label, id_number=f"PENDING-{unit.label}",
        phone="+254700000012", unit=unit, monthly_rent=D("50655"),
        move_in_date="2026-07-21", status=status,
    )


def _status(unit):
    unit.refresh_from_db()
    return unit.status


def test_a_tenant_on_notice_keeps_the_unit_occupied(arcade):
    unit = _unit(arcade, "MCW12")
    _tenant(unit, TenantStatus.NOTICE_GIVEN)

    recalculate_all_statuses()

    assert _status(unit) != UnitStatus.VACANT, "a unit still occupied under notice was vacated"


def test_a_unit_wrongly_vacated_under_notice_is_restored(arcade):
    unit = _unit(arcade, "MCW12", status=UnitStatus.VACANT)
    _tenant(unit, TenantStatus.NOTICE_GIVEN)

    recalculate_all_statuses()

    assert _status(unit) == UnitStatus.OCCUPIED_UNPAID


def test_a_unit_with_no_current_tenant_is_still_vacated(arcade):
    unit = _unit(arcade, "MCW04")
    _tenant(unit, TenantStatus.MOVED_OUT)

    recalculate_all_statuses()

    assert _status(unit) == UnitStatus.VACANT


def test_a_vacant_unit_with_no_tenant_stays_vacant(arcade):
    unit = _unit(arcade, "MCW05", status=UnitStatus.VACANT)

    recalculate_all_statuses()

    assert _status(unit) == UnitStatus.VACANT


def test_a_combined_member_follows_its_head_rather_than_being_vacated(arcade):
    head = _unit(arcade, "MCW07")
    member = _unit(arcade, "MCW08")
    member.combined_into = head
    member.save(update_fields=["combined_into"])
    _tenant(head, TenantStatus.ACTIVE)

    recalculate_all_statuses()

    assert _status(member) == _status(head)
    assert _status(member) != UnitStatus.VACANT
