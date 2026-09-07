"""A maintenance request's auto-created expense is booked to its unit."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.buildings.models import Building, MaintenanceRequest, Unit, UnitStatus
from apps.expenses.models import Expense

User = get_user_model()


class MaintenanceExpenseUnitTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="mnt", email="mnt@test.com", password="testpass123!", role="owner",
        )
        cls.building = Building.objects.create(name="Maintenance Block", total_floors=1)
        cls.unit = Unit.objects.create(
            building=cls.building, label="MB1",
            monthly_rent=Decimal("10000"), status=UnitStatus.VACANT,
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_costed_request_books_the_expense_to_the_unit(self):
        """The work order names a unit, so the cost it generates should too."""
        resp = self.client.post("/api/maintenance/", {
            "unit": self.unit.id,
            "description": "Replace kitchen tap",
            "cost": "3500.00",
            "reported_date": "2026-04-15",
            "status": "open",
        }, format="json")
        assert resp.status_code == status.HTTP_201_CREATED

        request = MaintenanceRequest.objects.get(pk=resp.json()["id"])
        assert request.expense is not None
        assert request.expense.unit_id == self.unit.id
        assert request.expense.building_id == self.building.id

    def test_free_request_creates_no_expense(self):
        resp = self.client.post("/api/maintenance/", {
            "unit": self.unit.id,
            "description": "Inspection, no cost",
            "cost": "0",
            "reported_date": "2026-04-15",
            "status": "open",
        }, format="json")
        assert resp.status_code == status.HTTP_201_CREATED
        assert MaintenanceRequest.objects.get(pk=resp.json()["id"]).expense is None
        assert not Expense.objects.filter(unit=self.unit).exists()
