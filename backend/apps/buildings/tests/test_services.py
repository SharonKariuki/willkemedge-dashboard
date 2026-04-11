"""Tests for status transition service and recalculation logic."""
from decimal import Decimal

from django.test import TestCase

from apps.buildings.models import Building, Unit, UnitStatus
from apps.buildings.services import (
    InvalidStatusTransition,
    move_in,
    move_out,
    recalculate_unit_status,
    transition_status,
)


class StatusTransitionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.building = Building.objects.create(name="Test Block", total_floors=2)

    def _make_unit(self, status=UnitStatus.VACANT, rent=10000):
        return Unit.objects.create(
            building=self.building,
            label=f"U{Unit.objects.count() + 1}",
            monthly_rent=Decimal(rent),
            status=status,
        )

    # --- move_in / move_out ------------------------------------------------

    def test_move_in_sets_occupied_unpaid(self):
        unit = self._make_unit(UnitStatus.VACANT)
        move_in(unit)
        unit.refresh_from_db()
        assert unit.status == UnitStatus.OCCUPIED_UNPAID

    def test_move_in_from_occupied_raises(self):
        unit = self._make_unit(UnitStatus.OCCUPIED_PAID)
        with self.assertRaises(InvalidStatusTransition):
            move_in(unit)

    def test_move_out_from_any_occupied_state(self):
        for starting in [
            UnitStatus.OCCUPIED_UNPAID,
            UnitStatus.OCCUPIED_PARTIAL,
            UnitStatus.OCCUPIED_PAID,
            UnitStatus.ARREARS,
        ]:
            unit = self._make_unit(starting)
            move_out(unit)
            unit.refresh_from_db()
            assert unit.status == UnitStatus.VACANT

    def test_move_out_from_vacant_raises(self):
        unit = self._make_unit(UnitStatus.VACANT)
        with self.assertRaises(InvalidStatusTransition):
            move_out(unit)

    # --- explicit transition_status ----------------------------------------

    def test_transition_no_op_same_status(self):
        unit = self._make_unit(UnitStatus.VACANT)
        transition_status(unit, UnitStatus.VACANT)
        unit.refresh_from_db()
        assert unit.status == UnitStatus.VACANT

    def test_invalid_transition_raises(self):
        unit = self._make_unit(UnitStatus.VACANT)
        with self.assertRaises(InvalidStatusTransition):
            transition_status(unit, UnitStatus.OCCUPIED_PAID)

    def test_valid_transition_occupied_unpaid_to_partial(self):
        unit = self._make_unit(UnitStatus.OCCUPIED_UNPAID)
        transition_status(unit, UnitStatus.OCCUPIED_PARTIAL)
        unit.refresh_from_db()
        assert unit.status == UnitStatus.OCCUPIED_PARTIAL

    def test_valid_transition_partial_to_paid(self):
        unit = self._make_unit(UnitStatus.OCCUPIED_PARTIAL)
        transition_status(unit, UnitStatus.OCCUPIED_PAID)
        unit.refresh_from_db()
        assert unit.status == UnitStatus.OCCUPIED_PAID

    def test_valid_transition_to_arrears(self):
        unit = self._make_unit(UnitStatus.OCCUPIED_UNPAID)
        transition_status(unit, UnitStatus.ARREARS)
        unit.refresh_from_db()
        assert unit.status == UnitStatus.ARREARS

    # --- recalculate_unit_status -------------------------------------------

    def test_recalculate_zero_payment(self):
        unit = self._make_unit(UnitStatus.OCCUPIED_PAID, rent=10000)
        recalculate_unit_status(unit, Decimal("0"))
        unit.refresh_from_db()
        assert unit.status == UnitStatus.OCCUPIED_UNPAID

    def test_recalculate_partial_payment(self):
        unit = self._make_unit(UnitStatus.OCCUPIED_UNPAID, rent=10000)
        recalculate_unit_status(unit, Decimal("5000"))
        unit.refresh_from_db()
        assert unit.status == UnitStatus.OCCUPIED_PARTIAL

    def test_recalculate_full_payment(self):
        unit = self._make_unit(UnitStatus.OCCUPIED_UNPAID, rent=10000)
        recalculate_unit_status(unit, Decimal("10000"))
        unit.refresh_from_db()
        assert unit.status == UnitStatus.OCCUPIED_PAID

    def test_recalculate_overpayment(self):
        unit = self._make_unit(UnitStatus.OCCUPIED_UNPAID, rent=10000)
        recalculate_unit_status(unit, Decimal("15000"))
        unit.refresh_from_db()
        assert unit.status == UnitStatus.OCCUPIED_PAID

    def test_recalculate_skips_vacant(self):
        unit = self._make_unit(UnitStatus.VACANT, rent=10000)
        recalculate_unit_status(unit, Decimal("10000"))
        unit.refresh_from_db()
        assert unit.status == UnitStatus.VACANT


class UnitViewSetTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        cls.user = User.objects.create_user(
            username="tester", email="test@example.com", password="testpass123!"
        )
        cls.building = Building.objects.create(name="API Block", total_floors=2)
        Unit.objects.create(
            building=cls.building, label="X1", monthly_rent=10000, status=UnitStatus.VACANT
        )
        Unit.objects.create(
            building=cls.building, label="X2", monthly_rent=15000, status=UnitStatus.OCCUPIED_PAID
        )

    def setUp(self):
        from rest_framework.test import APIClient
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_list_units(self):
        resp = self.client.get("/api/units/")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_filter_by_status(self):
        resp = self.client.get("/api/units/", {"status": "vacant"})
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_status_summary(self):
        resp = self.client.get("/api/units/status-summary/")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert body["vacant"] == 1
        assert body["occupied_paid"] == 1

    def test_list_buildings(self):
        resp = self.client.get("/api/buildings/")
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["unit_count"] == 2

    def test_building_detail_has_units(self):
        resp = self.client.get(f"/api/buildings/{self.building.id}/")
        assert resp.status_code == 200
        assert len(resp.json()["units"]) == 2

    def test_create_unit(self):
        resp = self.client.post("/api/units/", {
            "building": self.building.id,
            "label": "X3",
            "monthly_rent": "20000.00",
            "unit_type": "1br",
        })
        assert resp.status_code == 201
        assert resp.json()["status"] == "vacant"

    def test_unauthenticated_is_denied(self):
        from rest_framework.test import APIClient
        anon = APIClient()
        resp = anon.get("/api/units/")
        assert resp.status_code == 401
