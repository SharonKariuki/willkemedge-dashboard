"""
The deposit card's data contract.

The card used to show `deposit_paid` with nothing to hold it against, so a
residential deposit sitting at zero looked no different from one paid in full.
These pin the three derived fields it now reads.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.buildings.models import Building, Unit, UnitClassification, UnitStatus
from apps.tenants.models import Tenant, TenantStatus

User = get_user_model()
D = Decimal


class DepositCardFieldsTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="deposits", email="deposits@test.com",
            password="testpass123!", role="owner",
        )
        cls.building = Building.objects.create(name="Wilkem Edge", code="WED", total_floors=2)

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _let(self, label, classification, rent, held):
        unit = Unit.objects.create(
            building=self.building, label=label, monthly_rent=D(rent),
            classification=classification, status=UnitStatus.OCCUPIED_UNPAID,
        )
        return Tenant.objects.create(
            first_name=label, last_name="Tenant", id_number=f"ID-{label}",
            phone=f"+2547111111{len(label):02d}", unit=unit, monthly_rent=D(rent),
            deposit_paid=D(held), move_in_date="2026-07-01", status=TenantStatus.ACTIVE,
        )

    def _detail(self, tenant):
        resp = self.client.get(f"/api/tenants/{tenant.id}/")
        assert resp.status_code == status.HTTP_200_OK, resp.content
        return resp.json()

    def test_residential_expects_one_months_rent(self):
        tenant = self._let("WED01", UnitClassification.RESIDENTIAL, "20000", "20000")

        body = self._detail(tenant)

        assert body["deposit_months"] == 1
        assert Decimal(str(body["expected_deposit"])) == D("20000.00")
        assert Decimal(str(body["deposit_shortfall"])) == D("0.00")

    def test_commercial_still_expects_three_months_rent(self):
        """Matasia Commercial is the exception the one-month rule is against."""
        tenant = self._let("WED02", UnitClassification.BUSINESS, "24000", "72000")

        body = self._detail(tenant)

        assert body["deposit_months"] == 3
        assert Decimal(str(body["expected_deposit"])) == D("72000.00")
        assert Decimal(str(body["deposit_shortfall"])) == D("0.00")

    def test_an_unrecorded_residential_deposit_reports_a_full_shortfall(self):
        tenant = self._let("WED03", UnitClassification.RESIDENTIAL, "18000", "0")

        body = self._detail(tenant)

        assert Decimal(str(body["deposit_shortfall"])) == D("18000.00")
        assert Decimal(str(body["deposit_paid"])) == D("0.00"), "cash received was restated"

    def test_the_endpoint_never_restates_what_was_received(self):
        """Reading the card must not quietly round a deposit up to policy."""
        tenant = self._let("WED04", UnitClassification.RESIDENTIAL, "18000", "5000")

        self._detail(tenant)

        tenant.refresh_from_db()
        assert tenant.deposit_paid == D("5000.00")
