"""
Tests for DashboardSummaryView + report accuracy (F4 / F10 / F11).

Covers the owner's daily KPI screen, which previously had no tests:
- deposits (a liability) must not count as rental income or collection (F4)
- units under maintenance are not "occupied" (F10)
- commercial expected rent is grossed up so collection % can't exceed 100 (F11)
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.buildings.models import Building, Unit, UnitClassification, UnitStatus
from apps.payments.models import Payment, PaymentSource, PaymentType
from apps.tenants.models import Tenant, TenantStatus

User = get_user_model()


class DashboardSummaryTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="admin", email="admin@test.com", password="testpass123!"
        )
        cls.building = Building.objects.create(name="Summary Block", total_floors=2)

        # 5 units spanning every occupancy state.
        cls.res = Unit.objects.create(
            building=cls.building, label="S1", monthly_rent=Decimal("10000"),
            classification=UnitClassification.RESIDENTIAL, status=UnitStatus.OCCUPIED_PAID,
        )
        cls.com = Unit.objects.create(
            building=cls.building, label="S2", monthly_rent=Decimal("20000"),
            classification=UnitClassification.BUSINESS, status=UnitStatus.OCCUPIED_PAID,
        )
        cls.arr = Unit.objects.create(
            building=cls.building, label="S3", monthly_rent=Decimal("8000"),
            classification=UnitClassification.RESIDENTIAL, status=UnitStatus.ARREARS,
        )
        cls.vacant = Unit.objects.create(
            building=cls.building, label="S4", monthly_rent=Decimal("9000"),
            classification=UnitClassification.RESIDENTIAL, status=UnitStatus.VACANT,
        )
        cls.maint = Unit.objects.create(
            building=cls.building, label="S5", monthly_rent=Decimal("9000"),
            classification=UnitClassification.RESIDENTIAL, status=UnitStatus.UNDER_MAINTENANCE,
        )

        cls.res_t = Tenant.objects.create(
            first_name="Res", last_name="T", id_number="DS1", phone="+254700001001",
            unit=cls.res, monthly_rent=Decimal("10000"), move_in_date="2026-01-01",
            status=TenantStatus.ACTIVE,
        )
        cls.com_t = Tenant.objects.create(
            first_name="Com", last_name="T", id_number="DS2", phone="+254700001002",
            unit=cls.com, monthly_rent=Decimal("20000"), move_in_date="2026-01-01",
            status=TenantStatus.ACTIVE,
        )
        cls.arr_t = Tenant.objects.create(
            first_name="Arr", last_name="T", id_number="DS3", phone="+254700001003",
            unit=cls.arr, monthly_rent=Decimal("8000"), move_in_date="2026-01-01",
            status=TenantStatus.ACTIVE,
        )

        now = timezone.now()
        cls.month, cls.year = now.month, now.year
        common = dict(
            payment_date=now.date(), period_month=cls.month, period_year=cls.year,
            source=PaymentSource.MPESA,
        )
        # Rent: residential 10,000 + commercial 23,200 (gross, incl 16% VAT).
        Payment.objects.create(
            tenant=cls.res_t, amount=Decimal("10000"), payment_type=PaymentType.RENT,
            reference="RENT-R", **common,
        )
        Payment.objects.create(
            tenant=cls.com_t, amount=Decimal("23200"), payment_type=PaymentType.RENT,
            reference="RENT-C", **common,
        )
        # A security deposit — must NOT count as income/collection.
        Payment.objects.create(
            tenant=cls.res_t, amount=Decimal("15000"), payment_type=PaymentType.DEPOSIT,
            reference="DEP-R", **common,
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _summary(self):
        resp = self.client.get("/api/dashboard/summary/")
        assert resp.status_code == 200
        return resp.json()

    def test_occupancy_excludes_under_maintenance(self):
        data = self._summary()
        kpis = data["kpis"]
        assert kpis["total_units"] == 5
        assert kpis["vacant"] == 1
        assert kpis["under_maintenance"] == 1
        # occupied = paid + paid + arrears (NOT vacant, NOT maintenance)
        assert kpis["occupied"] == 3

        occ = data["occupancy"]
        assert occ["under_maintenance"] == 1
        # every unit is accounted for exactly once
        assert (
            occ["vacant"] + occ["paid"] + occ["partial"]
            + occ["unpaid"] + occ["arrears"] + occ["under_maintenance"]
        ) == kpis["total_units"]

        building = data["buildings"][0]
        assert building["total"] == 5
        assert building["occupied"] == 3

    def test_collection_excludes_deposit_and_grosses_up_commercial(self):
        data = self._summary()
        kpis = data["kpis"]
        # Collected = rent only (10,000 + 23,200); the 15,000 deposit is excluded.
        assert kpis["collection_received"] == 33200.0
        # Expected = 10,000 + (20,000 x 1.16 = 23,200) + 8,000 = 41,200 (VAT-inclusive).
        assert kpis["collection_expected"] == 41200.0
        # 33,200 / 41,200 = 80.6% — and crucially, never above 100 for full payers.
        assert kpis["collection_percentage"] == 80.6
        assert kpis["collection_percentage"] <= 100

    def test_income_trend_excludes_deposit(self):
        data = self._summary()
        current = data["income_trend"][-1]
        assert current["month"] == f"{self.year}-{self.month:02d}"
        # Rent 33,200; deposit 15,000 excluded from income.
        assert current["amount"] == 33200.0

    def test_annual_income_report_excludes_deposit(self):
        resp = self.client.get("/api/reports/annual-income/", {"year": self.year})
        assert resp.status_code == 200
        monthly = {row["month"]: row["total"] for row in resp.json()["monthly"]}
        # Income for the current month is rent only — the 15,000 deposit is out.
        assert monthly[self.month] == 33200.0

    def test_occupancy_report_excludes_under_maintenance(self):
        resp = self.client.get("/api/reports/occupancy/")
        assert resp.status_code == 200
        building = resp.json()["buildings"][0]
        assert building["total"] == 5
        assert building["occupied"] == 3  # not 4 — maintenance unit is not occupied

    def test_profit_loss_income_is_net_of_vat_and_excludes_deposit(self):
        """Legacy P&L income must match the ledger basis: commercial rent net of
        VAT, deposits excluded (F9)."""
        resp = self.client.get(
            "/api/reports/profit-loss/", {"month": self.month, "year": self.year}
        )
        assert resp.status_code == 200
        # Commercial 23,200 gross -> 20,000 net + residential 10,000 = 30,000.
        # The 15,000 deposit is excluded. (Was 33,200 gross before the fix.)
        assert abs(resp.json()["income"] - 30000) < 0.5
