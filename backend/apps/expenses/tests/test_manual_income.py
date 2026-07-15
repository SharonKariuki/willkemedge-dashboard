"""
Manual income/expense for farms + Baobab Karen (Barclay F6).

Acceptance criteria:
  - staff can post manual income AND expenses for FSE/FMM/FNN farms
  - KRN (Baobab Karen) allows expenses only — income entry is disabled with a
    clear message
  - all entries carry a COA code
  - entries appear in the relevant property ledger
"""
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.buildings.models import Building, PropertyType
from apps.expenses.models import Account, ManualIncome
from apps.ledger.models import JournalEntry

User = get_user_model()


@pytest.fixture
def client(db):
    user = User.objects.create_user(username="staff", email="s@t.com", password="pw123456!")
    c = APIClient()
    c.force_authenticate(user=user)
    return c


@pytest.fixture
def farm(db):
    return Building.objects.create(
        name="Wilkem Navillus Farm, Soy", code="FS",
        property_type=PropertyType.FARM, total_floors=1,
    )


@pytest.fixture
def karen(db):
    return Building.objects.create(
        name="Wilkem Residence, The Baobab Karen", code="KN",
        property_type=PropertyType.EXPENSE_ONLY, total_floors=1,
    )


@pytest.fixture
def income_account(db):
    # 4150 is seeded by the COA migration; use it as the income GL account.
    return Account.objects.get(code="4150")


@pytest.mark.django_db
class TestFarmIncome:
    def test_farm_can_record_manual_income(self, client, farm, income_account):
        resp = client.post("/api/manual-income/", {
            "date": "2026-06-10", "building": farm.id, "account": income_account.id,
            "amount": "45000.00", "description": "Maize sale",
            "period_month": 6, "period_year": 2026,
        }, format="json")
        assert resp.status_code == 201
        assert ManualIncome.objects.filter(building=farm).count() == 1

    def test_manual_income_posts_to_the_ledger(self, client, farm, income_account):
        resp = client.post("/api/manual-income/", {
            "date": "2026-06-10", "building": farm.id, "account": income_account.id,
            "amount": "45000.00", "description": "Maize sale",
            "period_month": 6, "period_year": 2026,
        }, format="json")
        income = ManualIncome.objects.get(pk=resp.json()["id"])
        entry = JournalEntry.objects.get(source_type="manual_income", source_id=income.pk)
        legs = {line.account.code: (line.debit, line.credit) for line in entry.lines.all()}
        assert legs["1020"] == (Decimal("45000.00"), Decimal("0.00"))
        assert legs["4150"] == (Decimal("0.00"), Decimal("45000.00"))
        assert entry.building_id == farm.id  # appears in the farm's ledger

    def test_income_requires_a_coa_account(self, client, farm):
        resp = client.post("/api/manual-income/", {
            "date": "2026-06-10", "building": farm.id,
            "amount": "1000.00", "description": "No account",
            "period_month": 6, "period_year": 2026,
        }, format="json")
        assert resp.status_code == 400
        assert "account" in resp.json()

    def test_deleting_income_reverses_the_ledger_entry(self, client, farm, income_account):
        resp = client.post("/api/manual-income/", {
            "date": "2026-06-10", "building": farm.id, "account": income_account.id,
            "amount": "45000.00", "description": "Maize sale",
            "period_month": 6, "period_year": 2026,
        }, format="json")
        iid = resp.json()["id"]
        client.delete(f"/api/manual-income/{iid}/")
        assert JournalEntry.objects.filter(
            source_type="manual_income", source_id=iid, kind="reversal"
        ).exists()


@pytest.mark.django_db
class TestKarenIncomeDisabled:
    def test_karen_rejects_income(self, client, karen, income_account):
        resp = client.post("/api/manual-income/", {
            "date": "2026-06-10", "building": karen.id, "account": income_account.id,
            "amount": "1000.00", "description": "Should be blocked",
            "period_month": 6, "period_year": 2026,
        }, format="json")
        assert resp.status_code == 400
        assert "expenses-only" in str(resp.json())
        assert not ManualIncome.objects.filter(building=karen).exists()

    def test_allows_income_flag(self, karen, farm):
        assert farm.allows_income is True
        assert karen.allows_income is False


@pytest.mark.django_db
class TestKarenExpensesStillWork:
    def test_karen_can_record_expenses(self, client, karen):
        from apps.expenses.models import ExpenseCategory

        cat = ExpenseCategory.objects.create(
            name="Repairs & Maintenance", account=Account.objects.get(code="5200"),
        )
        resp = client.post("/api/expenses/", {
            "date": "2026-06-10", "building": karen.id, "category": cat.id,
            "amount": "8000.00", "description": "Roof repair",
            "period_month": 6, "period_year": 2026,
        }, format="json")
        assert resp.status_code == 201
