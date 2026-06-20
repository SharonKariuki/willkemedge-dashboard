"""Tests for dashboard financial report computations.

Seeds payments and expenses, then asserts the reported numbers are correct —
not merely that the endpoint returns 200.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework.test import APIClient, APITestCase

from apps.buildings.models import Building, Unit, UnitClassification, UnitStatus
from apps.expenses.models import Account, Expense, ExpenseCategory
from apps.payments.services import process_payment
from apps.tenants.models import Tenant

User = get_user_model()

MONTH = 4
YEAR = 2026


class ReportsTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="admin", email="admin@test.com", password="testpass123!"
        )
        cls.building = Building.objects.create(name="Block A", total_floors=2)

        cls.res_unit = Unit.objects.create(
            building=cls.building, label="A1", monthly_rent=Decimal("10000"),
            status=UnitStatus.OCCUPIED_UNPAID, classification=UnitClassification.RESIDENTIAL,
        )
        cls.com_unit = Unit.objects.create(
            building=cls.building, label="A2", monthly_rent=Decimal("20000"),
            status=UnitStatus.OCCUPIED_UNPAID, classification=UnitClassification.BUSINESS,
        )

        cls.res_tenant = Tenant.objects.create(
            first_name="Res", last_name="Tenant", id_number="R1",
            phone="+254700000001", unit=cls.res_unit,
            monthly_rent=Decimal("10000"), move_in_date="2026-01-01",
        )
        cls.com_tenant = Tenant.objects.create(
            first_name="Com", last_name="Tenant", id_number="C1",
            phone="+254700000002", unit=cls.com_unit,
            monthly_rent=Decimal("20000"), move_in_date="2026-01-01",
        )

        # Residential pays full 10000; commercial pays partial 12000 of 20000.
        process_payment(
            tenant=cls.res_tenant, amount=Decimal("10000"),
            payment_date="2026-04-05", period_month=MONTH, period_year=YEAR,
        )
        process_payment(
            tenant=cls.com_tenant, amount=Decimal("12000"),
            payment_date="2026-04-06", period_month=MONTH, period_year=YEAR,
        )

        # Expenses: 5200 repairs 3000, 5300 utilities 1500.
        # COA accounts are seeded by data migration — reuse them.
        repairs = Account.objects.get(code="5200")
        utilities = Account.objects.get(code="5300")
        cat_repairs = ExpenseCategory.objects.create(name="Repairs", account=repairs)
        cat_utils = ExpenseCategory.objects.create(name="Utilities", account=utilities)
        Expense.objects.create(
            date="2026-04-10", category=cat_repairs, amount=Decimal("3000"),
            description="Roof", period_month=MONTH, period_year=YEAR, building=cls.building,
        )
        Expense.objects.create(
            date="2026-04-11", category=cat_utils, amount=Decimal("1500"),
            description="Water", period_month=MONTH, period_year=YEAR, building=cls.building,
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    # --- Monthly collection --------------------------------------------

    def test_monthly_collection_totals(self):
        resp = self.client.get("/api/reports/monthly-collection/", {"month": MONTH, "year": YEAR})
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 2
        # 10000 + 12000 collected.
        assert body["total"] == 22000.0

    # --- Annual income -------------------------------------------------

    def test_annual_income_grand_total(self):
        resp = self.client.get("/api/reports/annual-income/", {"year": YEAR})
        assert resp.status_code == 200
        body = resp.json()
        assert body["grand_total"] == 22000.0
        april = next(m for m in body["monthly"] if m["month"] == MONTH)
        assert april["total"] == 22000.0

    # --- Arrears -------------------------------------------------------

    def test_arrears_report_balance(self):
        resp = self.client.get("/api/reports/arrears/")
        assert resp.status_code == 200
        body = resp.json()
        # Only the commercial tenant owes (20000 - 12000 = 8000).
        assert body["count"] == 1
        assert body["total_balance"] == 8000.0
        assert body["arrears"][0]["balance"] == 8000.0

    # --- Profit & Loss (monthly) ---------------------------------------

    def test_profit_loss_monthly_net(self):
        resp = self.client.get("/api/reports/profit-loss/", {"month": MONTH, "year": YEAR})
        assert resp.status_code == 200
        body = resp.json()
        assert body["income"] == 22000.0
        assert body["total_expenses"] == 4500.0  # 3000 + 1500
        assert body["net_profit"] == 17500.0

    def test_profit_loss_annual_grand_net(self):
        resp = self.client.get("/api/reports/profit-loss/", {"mode": "annual", "year": YEAR})
        assert resp.status_code == 200
        body = resp.json()
        assert body["grand_income"] == 22000.0
        assert body["grand_expenses"] == 4500.0
        assert body["grand_net"] == 17500.0

    # --- Accounting P&L tab (rent split by classification) -------------

    def test_accounting_pnl_rent_split(self):
        resp = self.client.get("/api/reports/accounting/", {"tab": "pnl", "month": MONTH, "year": YEAR})
        assert resp.status_code == 200
        body = resp.json()
        # All payments are RENT type by default; split by unit classification.
        assert body["residential_income"] == 10000.0
        assert body["commercial_income"] == 12000.0
        assert body["rental_income"] == 22000.0
        assert body["total_expenses"] == 4500.0
        assert body["net_profit"] == 17500.0

    # --- Trial balance -------------------------------------------------

    def test_trial_balance_numbers(self):
        # Trial balance is sourced from the double-entry general ledger
        # (JournalLine), so it is cash-basis: only the 22000 actually collected
        # and the 4500 of expenses paid are posted — no accrued arrears.
        resp = self.client.get("/api/reports/trial-balance/", {"month": MONTH, "year": YEAR})
        assert resp.status_code == 200
        body = resp.json()
        # Accounts are keyed by "<code> <name>" from the Chart of Accounts.
        accounts = {a["account"]: a for a in body["accounts"]}
        # Operating bank: DR 22000 collected, CR 4500 paid out for expenses.
        assert accounts["1020 Operating Bank Account"]["debit"] == 22000.0
        assert accounts["1020 Operating Bank Account"]["credit"] == 4500.0
        # Rental income is split by unit classification.
        assert accounts["4110 Residential Rental Income"]["credit"] == 10000.0
        assert accounts["4120 Commercial Rental Income"]["credit"] == 12000.0
        # Expense legs debit their GL accounts.
        assert accounts["5200 Repairs & Maintenance"]["debit"] == 3000.0
        assert accounts["5300 Utilities (Common Areas)"]["debit"] == 1500.0
        # The defining invariant of double-entry bookkeeping.
        assert body["total_debit"] == body["total_credit"] == 26500.0
        assert body["is_balanced"] is True

    # --- Expense breakdown ---------------------------------------------

    def test_expense_breakdown_percentages(self):
        resp = self.client.get("/api/reports/expense-breakdown/", {"month": MONTH, "year": YEAR})
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_expenses"] == 4500.0
        cats = {c["category"]: c for c in body["categories"]}
        # Repairs 3000 / 4500 = 66.7%
        assert cats["Repairs"]["total"] == 3000.0
        assert cats["Repairs"]["percentage"] == 66.7

    # --- Tenant payment history ----------------------------------------

    def test_tenant_history_total_paid(self):
        resp = self.client.get(f"/api/reports/tenant-history/{self.res_tenant.id}/")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_paid"] == 10000.0
        assert body["tenant"]["monthly_rent"] == 10000.0

    # --- Occupancy -----------------------------------------------------

    def test_occupancy_rate(self):
        resp = self.client.get("/api/reports/occupancy/")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_units"] == 2
        block = next(b for b in body["buildings"] if b["name"] == "Block A")
        # Both units occupied → 100%.
        assert block["occupied"] == 2
        assert block["rate"] == 100.0

    # --- Auth ----------------------------------------------------------

    def test_unauthenticated_denied(self):
        anon = APIClient()
        assert anon.get("/api/reports/arrears/").status_code == 401
