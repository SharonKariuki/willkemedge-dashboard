"""Filtering the roster to one property lists its units ground floor first."""
import datetime as dt
from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework.test import APIClient, APITestCase

from apps.buildings.models import Building, Unit, UnitStatus
from apps.buildings.unit_order import unit_sort_key
from apps.tenants.models import Tenant, TenantStatus

User = get_user_model()


class UnitSortKeyTests(APITestCase):
    def _order(self, labels, code=None):
        return sorted(labels, key=lambda label: unit_sort_key(label, code))

    def test_road_block_ground_floor_leads(self):
        self.assertEqual(
            self._order(["RB301", "RB101", "RB08", "RB211", "RB01"], "RB"),
            ["RB01", "RB08", "RB101", "RB211", "RB301"],
        )

    def test_zero_padded_ground_floor_also_leads(self):
        self.assertEqual(
            self._order(["RB101", "RB009", "RB001"], "RB"),
            ["RB001", "RB009", "RB101"],
        )

    def test_units_within_a_floor_run_in_numeric_not_text_order(self):
        self.assertEqual(
            self._order(["RB111", "RB102", "RB11", "RB2"], "RB"),
            ["RB2", "RB11", "RB102", "RB111"],
        )

    def test_commercial_ground_floor_beats_first_floor(self):
        # MCG = ground, MCF = first — plain text sort would put F before G.
        self.assertEqual(
            self._order(["MCF01", "MCG10", "MCG02", "MCF20"], "MC"),
            ["MCG02", "MCG10", "MCF01", "MCF20"],
        )

    def test_commercial_labels_without_the_building_prefix(self):
        self.assertEqual(
            self._order(["F-03", "G-10", "G-02", "F-13B"]),
            ["G-02", "G-10", "F-03", "F-13B"],
        )

    def test_donholm_letter_units_stay_paired_by_floor(self):
        self.assertEqual(
            self._order(["DON2A", "DON1B", "DON4A", "DON1A"], "DON"),
            ["DON1A", "DON1B", "DON2A", "DON4A"],
        )

    def test_blank_label_does_not_raise(self):
        self.assertEqual(unit_sort_key("")[0], 0)


class TenantListOrderTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="roster", email="roster@test.com", password="testpass123!", role="owner"
        )
        cls.building = Building.objects.create(name="Road Block", code="RB", total_floors=5)
        cls.other = Building.objects.create(name="Khaoya", code="KH", total_floors=1)
        # Created out of order, and with move-in dates that fight the unit order,
        # so a pass-through of the default ordering would fail this test.
        cls.labels = ["RB301", "RB101", "RB02", "RB211", "RB01"]
        for i, label in enumerate(cls.labels):
            unit = Unit.objects.create(
                building=cls.building,
                label=label,
                monthly_rent=Decimal("10000"),
                status=UnitStatus.OCCUPIED_PAID,
            )
            Tenant.objects.create(
                first_name="T", last_name=label, id_number=f"ID{i}",
                phone=f"+25470000000{i}", unit=unit,
                monthly_rent=Decimal("10000"),
                move_in_date=dt.date(2026, 1, 1) + dt.timedelta(days=i),
                status=TenantStatus.ACTIVE,
            )
        kh = Unit.objects.create(
            building=cls.other, label="KH01",
            monthly_rent=Decimal("10000"), status=UnitStatus.OCCUPIED_PAID,
        )
        Tenant.objects.create(
            first_name="T", last_name="KH01", id_number="IDKH", phone="+254700000099",
            unit=kh, monthly_rent=Decimal("10000"),
            move_in_date=dt.date(2026, 1, 1), status=TenantStatus.ACTIVE,
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_building_filter_lists_units_ground_floor_first(self):
        resp = self.client.get(f"/api/tenants/?building={self.building.id}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            [row["unit_label"] for row in resp.data],
            ["RB01", "RB02", "RB101", "RB211", "RB301"],
        )

    def test_moved_out_tenants_still_sit_below_the_current_roster(self):
        moved = Tenant.objects.get(last_name="RB01")
        moved.status = TenantStatus.MOVED_OUT
        moved.save(update_fields=["status"])
        resp = self.client.get(f"/api/tenants/?building={self.building.id}")
        self.assertEqual(
            [row["unit_label"] for row in resp.data],
            ["RB02", "RB101", "RB211", "RB301", "RB01"],
        )

    def test_csv_export_matches_the_order_on_screen(self):
        resp = self.client.get(f"/api/tenants/export/?building={self.building.id}")
        self.assertEqual(resp.status_code, 200)
        rows = resp.content.decode().splitlines()[1:]
        self.assertEqual(
            [r.split(",")[2] for r in rows if r],
            ["RB01", "RB02", "RB101", "RB211", "RB301"],
        )

    def test_unfiltered_list_keeps_the_portfolio_wide_ordering(self):
        resp = self.client.get("/api/tenants/")
        self.assertEqual(resp.status_code, 200)
        # Newest move-in first, as before — unit order would interleave buildings.
        self.assertEqual(resp.data[0]["unit_label"], "RB01")
        self.assertEqual(len(resp.data), 6)
