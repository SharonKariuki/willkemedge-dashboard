"""Tests for the expenses app: Account (read-only), ExpenseCategory & Expense CRUD."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.buildings.models import Building, Unit, UnitStatus
from apps.expenses.models import Account, AccountType, Expense, ExpenseCategory

User = get_user_model()


class ExpensesAPITests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="admin", email="admin@test.com", password="testpass123!"
        )
        # The Chart of Accounts is seeded via data migration; reuse a posting
        # account rather than recreating one (codes are unique).
        cls.repairs_acct = Account.objects.get(code="5200")
        cls.inactive_acct = Account.objects.create(
            code="5999", name="Defunct", account_type=AccountType.EXPENSE,
            is_active=False,
        )
        cls.category = ExpenseCategory.objects.create(
            name="Plumbing", account=cls.repairs_acct,
        )
        cls.building = Building.objects.create(name="Block A", total_floors=2)
        Unit.objects.create(
            building=cls.building, label="A1",
            monthly_rent=Decimal("10000"), status=UnitStatus.VACANT,
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    # --- Accounts (read-only) ------------------------------------------

    def test_accounts_list_excludes_inactive(self):
        resp = self.client.get("/api/accounting/accounts/")
        assert resp.status_code == 200
        codes = {a["code"] for a in resp.json()}
        assert "5200" in codes
        assert "5999" not in codes  # inactive filtered out

    def test_accounts_filter_by_type(self):
        resp = self.client.get("/api/accounting/accounts/", {"type": "income"})
        assert resp.status_code == 200
        assert resp.json()  # COA seeds income accounts
        assert all(a["account_type"] == "income" for a in resp.json())

    def test_accounts_are_read_only(self):
        resp = self.client.post("/api/accounting/accounts/", {
            "code": "9999", "name": "Hack", "account_type": "expense",
        }, format="json")
        assert resp.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    # --- Expense categories are COA-locked (read-only) ------------------

    def test_categories_are_read_only(self):
        """Categories are a fixed, COA-locked set seeded by `seed_coa`.

        They used to be creatable over the API, which let a caller add one with
        no GL account — expenses booked under it were then silently dropped by
        the ledger. Creation now returns 405; the set changes via seed_coa.
        """
        resp = self.client.post("/api/expenses/categories/", {
            "name": "Electricity", "account": self.repairs_acct.id,
        }, format="json")
        assert resp.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    def test_categories_list_exposes_their_gl_code(self):
        resp = self.client.get("/api/expenses/categories/")
        assert resp.status_code == status.HTTP_200_OK
        row = next(r for r in resp.json() if r["id"] == self.category.id)
        assert row["account_code"] == "5200"
        assert row["account_name"] == "Repairs & Maintenance"

    # --- Expense CRUD + serializer validation --------------------------

    def _expense_payload(self, **overrides):
        base = {
            "date": "2026-04-15",
            "category": self.category.id,
            "amount": "1500.50",
            "description": "Fix leaking tap",
            "period_month": 4,
            "period_year": 2026,
        }
        base.update(overrides)
        return base

    def test_create_expense_persists_decimal_amount(self):
        resp = self.client.post("/api/expenses/", self._expense_payload(), format="json")
        assert resp.status_code == status.HTTP_201_CREATED
        exp = Expense.objects.get(pk=resp.json()["id"])
        assert exp.amount == Decimal("1500.50")
        assert resp.json()["category_name"] == "Plumbing"

    def test_negative_amount_rejected(self):
        resp = self.client.post(
            "/api/expenses/", self._expense_payload(amount="-10"), format="json"
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_invalid_month_rejected(self):
        resp = self.client.post(
            "/api/expenses/", self._expense_payload(period_month=13), format="json"
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_invalid_year_rejected(self):
        resp = self.client.post(
            "/api/expenses/", self._expense_payload(period_year=1999), format="json"
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_filter_expenses_by_month_year(self):
        Expense.objects.create(
            date="2026-04-15", category=self.category, amount=Decimal("100"),
            description="April", period_month=4, period_year=2026,
        )
        Expense.objects.create(
            date="2026-05-15", category=self.category, amount=Decimal("200"),
            description="May", period_month=5, period_year=2026,
        )
        resp = self.client.get("/api/expenses/", {"month": 4, "year": 2026})
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["description"] == "April"

    def test_filter_expenses_by_building_none(self):
        Expense.objects.create(
            date="2026-04-15", category=self.category, amount=Decimal("100"),
            description="Portfolio-wide", period_month=4, period_year=2026,
            building=None,
        )
        Expense.objects.create(
            date="2026-04-15", category=self.category, amount=Decimal("100"),
            description="Block A", period_month=4, period_year=2026,
            building=self.building,
        )
        resp = self.client.get("/api/expenses/", {"building": "none"})
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["description"] == "Portfolio-wide"

    def test_update_and_delete_expense(self):
        create = self.client.post("/api/expenses/", self._expense_payload(), format="json")
        eid = create.json()["id"]
        upd = self.client.patch(f"/api/expenses/{eid}/", {"amount": "2000.00"}, format="json")
        assert upd.status_code == 200
        assert Expense.objects.get(pk=eid).amount == Decimal("2000.00")
        delete = self.client.delete(f"/api/expenses/{eid}/")
        assert delete.status_code == status.HTTP_204_NO_CONTENT
        assert not Expense.objects.filter(pk=eid).exists()

    def test_unauthenticated_denied(self):
        anon = APIClient()
        assert anon.get("/api/expenses/").status_code == 401
