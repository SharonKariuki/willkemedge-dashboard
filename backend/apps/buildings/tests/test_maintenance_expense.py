"""A maintenance request's auto-created expense is booked to its unit."""
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.buildings.models import Building, MaintenanceRequest, Unit, UnitStatus
from apps.expenses.models import Expense

User = get_user_model()


class MaintenanceExpenseUnitTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_coa", stdout=StringIO())
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


class MaintenanceExpenseLedgerTests(APITestCase):
    """A work order's cost must reach the general ledger, not just the Expenses page.

    It used to be booked under an ad-hoc "Maintenance & Repairs" category with no
    GL account, which the ledger signal silently skips.
    """

    @classmethod
    def setUpTestData(cls):
        call_command("seed_coa", stdout=StringIO())
        cls.user = User.objects.create_user(
            username="mntgl", email="mntgl@test.com", password="testpass123!", role="owner",
        )
        cls.building = Building.objects.create(name="Ledger Block", total_floors=1)
        cls.unit = Unit.objects.create(
            building=cls.building, label="LB1",
            monthly_rent=Decimal("10000"), status=UnitStatus.VACANT,
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _create(self, cost):
        resp = self.client.post("/api/maintenance/", {
            "unit": self.unit.id,
            "description": "Fix gutter",
            "cost": cost,
            "reported_date": "2026-09-10",
            "status": "open",
        }, format="json")
        assert resp.status_code == status.HTTP_201_CREATED, resp.content
        return MaintenanceRequest.objects.get(pk=resp.json()["id"])

    @staticmethod
    def _gl_5200(expense):
        from apps.ledger.models import JournalLine

        return sum(
            line.debit for line in JournalLine.objects.filter(
                entry__source_type="expense", entry__source_id=expense.pk,
                entry__kind="normal", account__code="5200",
            )
        )

    def test_cost_is_booked_under_the_coa_category_and_posted(self):
        from apps.expenses.models import ExpenseCategory

        request = self._create("2500.00")
        assert request.expense.category.name == "Repairs & Maintenance"
        assert request.expense.category.account.code == "5200"
        assert self._gl_5200(request.expense) == Decimal("2500.00")
        assert not ExpenseCategory.objects.filter(name="Maintenance & Repairs").exists()

    def test_changed_cost_reposts(self):
        request = self._create("2500.00")
        resp = self.client.patch(
            f"/api/maintenance/{request.pk}/", {"cost": "4000.00"}, format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        request.refresh_from_db()
        assert self._gl_5200(request.expense) == Decimal("4000.00")

    def test_cost_added_later_books_an_expense(self):
        request = self._create("0")
        assert request.expense is None
        self.client.patch(f"/api/maintenance/{request.pk}/", {"cost": "1200.00"}, format="json")
        request.refresh_from_db()
        assert request.expense is not None
        assert self._gl_5200(request.expense) == Decimal("1200.00")

    def test_cost_removed_reverses_the_expense(self):
        from apps.ledger.models import JournalEntry

        request = self._create("2500.00")
        expense_id = request.expense_id
        self.client.patch(f"/api/maintenance/{request.pk}/", {"cost": "0"}, format="json")
        request.refresh_from_db()
        assert request.expense is None
        assert not Expense.objects.filter(pk=expense_id).exists()
        assert JournalEntry.objects.filter(
            source_type="expense", source_id=expense_id, kind="reversal",
        ).exists()


class RepairMaintenanceExpensesCommandTests(APITestCase):
    """The repair moves old stray-category expenses onto 5200 and posts them."""

    def test_repairs_stray_category_expense(self):
        call_command("seed_coa", stdout=StringIO())
        from apps.expenses.models import ExpenseCategory
        from apps.ledger.models import JournalEntry

        building = Building.objects.create(name="Old Block", total_floors=1)
        unit = Unit.objects.create(
            building=building, label="OB1", monthly_rent=Decimal("9000"),
            status=UnitStatus.VACANT,
        )
        # Reproduce what the old code wrote: an unmapped category.
        stray = ExpenseCategory.objects.create(name="Maintenance & Repairs")
        expense = Expense.objects.create(
            date="2026-08-01", building=building, unit=unit, category=stray,
            amount=Decimal("3000.00"), description="Maintenance: old",
            reference="MNT-1", period_month=8, period_year=2026,
        )
        MaintenanceRequest.objects.create(
            unit=unit, description="old", cost=Decimal("3000.00"),
            reported_date="2026-08-01", expense=expense,
        )
        assert not JournalEntry.objects.filter(source_type="expense", source_id=expense.pk).exists()

        call_command("repair_maintenance_expenses", stdout=StringIO())
        expense.refresh_from_db()
        assert expense.category_id == stray.pk  # dry run wrote nothing

        call_command("repair_maintenance_expenses", "--apply", stdout=StringIO())
        expense.refresh_from_db()
        assert expense.category.name == "Repairs & Maintenance"
        assert JournalEntry.objects.filter(
            source_type="expense", source_id=expense.pk, kind="normal",
        ).count() == 1
        assert not ExpenseCategory.objects.filter(pk=stray.pk).exists()
