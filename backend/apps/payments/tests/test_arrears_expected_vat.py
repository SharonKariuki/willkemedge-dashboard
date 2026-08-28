"""The "expected" column must be the obligation the balance is measured against.

A commercial tenant's obligation is rent + 16% VAT, and `Arrears.balance` is
computed against that total. Both arrears tables reported `expected_rent` alone,
so a commercial row contradicted itself on screen: expected 15,000 less paid
6,990 displayed beside a balance of 10,410.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework.test import APIClient, APITestCase

from apps.buildings.models import Building, Unit, UnitClassification, UnitStatus
from apps.payments.models import Arrears
from apps.tenants.models import Tenant

User = get_user_model()


class ArrearsExpectedIncludesVatTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="vat-admin", email="vat@test.com", password="testpass123!", role="owner"
        )
        building = Building.objects.create(
            name="Wilkem Edge Business Arcade - Matasia Commercial", total_floors=2
        )
        unit = Unit.objects.create(
            building=building, label="MCG04", monthly_rent=Decimal("15000"),
            classification=UnitClassification.BUSINESS, status=UnitStatus.OCCUPIED_UNPAID,
        )
        cls.tenant = Tenant.objects.create(
            first_name="Fortify", last_name="Solutions", id_number="PENDING-MCG04",
            phone="+254700111222", unit=unit, monthly_rent=Decimal("15000"),
            move_in_date="2026-06-01",
        )
        # The live row: 15,000 base + 2,400 VAT, 6,990 received.
        Arrears.objects.create(
            tenant=cls.tenant, period_month=6, period_year=2026,
            expected_rent=Decimal("15000"), expected_vat=Decimal("2400"),
            amount_paid=Decimal("6990"), balance=Decimal("10410"), is_cleared=False,
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_payment_history_row_adds_up(self):
        row = self.client.get(
            f"/api/tenants/{self.tenant.pk}/payment-history/"
        ).json()["arrears"][0]

        assert Decimal(row["expected"]) == Decimal("17400.00")
        assert Decimal(row["expected"]) - Decimal(row["paid"]) == Decimal(row["balance"])
        assert Decimal(row["expected_rent"]) == Decimal("15000.00")
        assert Decimal(row["expected_vat"]) == Decimal("2400.00")

    def test_arrears_report_row_adds_up(self):
        row = self.client.get("/api/reports/arrears/").json()["arrears"][0]

        assert row["expected"] == 17400.0
        assert row["expected"] - row["paid"] == row["balance"]
        assert row["expected_vat"] == 2400.0

    def test_residential_row_is_unchanged(self):
        """No VAT on residential, so expected stays the base rent."""
        building = Building.objects.get(pk=self.tenant.unit.building_id)
        unit = Unit.objects.create(
            building=building, label="RB305", monthly_rent=Decimal("7000"),
            status=UnitStatus.OCCUPIED_UNPAID,
        )
        tenant = Tenant.objects.create(
            first_name="Sheldon", last_name="Mutai", id_number="PENDING-RB305",
            phone="+254707575747", unit=unit, monthly_rent=Decimal("7000"),
            move_in_date="2026-01-01",
        )
        Arrears.objects.create(
            tenant=tenant, period_month=7, period_year=2026,
            expected_rent=Decimal("7000"), expected_vat=Decimal("0"),
            amount_paid=Decimal("6000"), balance=Decimal("1000"), is_cleared=False,
        )

        row = self.client.get(
            f"/api/tenants/{tenant.pk}/payment-history/"
        ).json()["arrears"][0]

        assert Decimal(row["expected"]) == Decimal("7000.00")
        assert Decimal(row["expected"]) - Decimal(row["paid"]) == Decimal(row["balance"])
